from __future__ import annotations

import json
import os
import hashlib
import multiprocessing as mp
import socket
import signal
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


_NO_PROXY_OPENER: urllib.request.OpenerDirector | None = None
_NO_PROXY_OPENER_LOCK = threading.Lock()
DEFAULT_DEEPSEEK_MAX_ATTEMPTS = 10
DEFAULT_DEEPSEEK_RETRY_BACKOFF = 2.0
DEFAULT_DEEPSEEK_RETRY_BACKOFF_MAX = 30.0


class DeepSeekClientError(RuntimeError):
    pass


def load_dotenv(path: str | Path = ".env.local") -> None:
    """Tiny dotenv loader to avoid adding runtime dependencies."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


class DeepSeekDebugClient:
    """OpenAI-compatible DeepSeek chat client for local debugging.

    Secrets are read from environment variables or `.env.local`:
    - DEEPSEEK_API_KEY
    - DEEPSEEK_MODEL, default: deepseek-v4-pro (the official V4-Pro Preview API ID)
    - DEEPSEEK_BASE_URL, default: https://api.deepseek.com/v1
    """

    def __init__(self, api_key: str | None = None, model: str | None = None, base_url: str | None = None, timeout: int | None = None, max_retries: int | None = None, retry_backoff: float | None = None):
        load_dotenv()
        self.model = model or os.getenv("DEEPSEEK_MODEL", "deepseek-v4-pro")
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = (base_url or os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")).rstrip("/")
        default_timeout = 360 if "pro" in self.model else 120
        self.timeout = int(timeout or os.getenv("DEEPSEEK_TIMEOUT", default_timeout))
        self.max_retries = _resolve_max_retries(max_retries)
        self.retry_backoff = _resolve_float_env("DEEPSEEK_RETRY_BACKOFF", DEFAULT_DEEPSEEK_RETRY_BACKOFF, retry_backoff)
        self.retry_backoff_max = _resolve_float_env("DEEPSEEK_RETRY_BACKOFF_MAX", DEFAULT_DEEPSEEK_RETRY_BACKOFF_MAX)
        if not self.api_key and self.model == "fake":
            self.api_key = "fake-test-key"
        if not self.api_key:
            raise DeepSeekClientError("DEEPSEEK_API_KEY is not set. Put it in .env.local or export it in the shell.")

    def chat(self, messages: list[dict[str, str]], temperature: float = 0.0, max_tokens: int = 1024, json_mode: bool = False) -> dict[str, Any]:
        max_tokens = self._resolve_max_tokens(max_tokens)
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens and max_tokens > 0:
            payload["max_tokens"] = max_tokens
        self.last_payload = dict(payload)
        # Code-generation callers use fenced Workbench slots. Forcing JSON for
        # every Flash request changes that protocol and makes the slot parser
        # reject otherwise valid code. JSON output is therefore opt-in at the
        # call site, just as it is for the other provider clients.
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
            self.last_payload = dict(payload)
        try:
            return self._chat_payload(payload)
        except DeepSeekClientError as exc:
            if json_mode and "response_format" in payload and "response_format" in str(exc):
                payload = dict(payload)
                payload.pop("response_format", None)
                return self._chat_payload(payload)
            raise

    def _resolve_max_tokens(self, requested: int | None) -> int | None:
        override = os.getenv("DEEPSEEK_MAX_TOKENS")
        if override is not None:
            value = int(override)
            return None if value <= 0 else value
        if os.getenv("DEEPSEEK_DEFAULT_UNLIMITED_MAX_TOKENS", "1") not in {"0", "false", "False", "no"}:
            return None
        if requested is None or requested <= 0:
            return None
        if "pro" in self.model:
            return max(int(requested), int(os.getenv("DEEPSEEK_PRO_MIN_MAX_TOKENS", "16000")))
        return int(requested)

    def _chat_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        cache_path = self._cache_path(payload)
        if cache_path is not None and cache_path.exists():
            data = _local_cache_hit_response(json.loads(cache_path.read_text(encoding="utf-8")), cache_path)
            _write_deepseek_trace(
                payload=payload,
                response=data,
                cache_path=cache_path,
                event="local_cache_hit",
                latency_seconds=time.perf_counter() - started,
            )
            return data
        if _cache_only_enabled():
            error = (
                "DEEPSEEK_CACHE_ONLY is enabled and the local response cache missed"
                f" for key {cache_path.name if cache_path is not None else '<cache-disabled>'}."
            )
            _write_deepseek_trace(
                payload=payload,
                response=None,
                cache_path=cache_path,
                event="local_cache_miss_blocked",
                latency_seconds=time.perf_counter() - started,
                error=error,
            )
            raise DeepSeekClientError(error)
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            req = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                hard_timeout = _hard_timeout_seconds()
                if hard_timeout:
                    try:
                        data = _chat_payload_hard_timeout(payload, self.base_url, self.api_key, self.timeout, hard_timeout, str(cache_path) if cache_path is not None else None)
                    except DeepSeekClientError as exc:
                        if attempt >= self.max_retries:
                            error = f"DeepSeek request failed after {attempt + 1} attempts: {exc}"
                            _write_deepseek_trace(
                                payload=payload,
                                response=None,
                                cache_path=cache_path,
                                event="api_error",
                                latency_seconds=time.perf_counter() - started,
                                error=error,
                            )
                            raise DeepSeekClientError(error) from exc
                        last_error = exc
                        time.sleep(self._retry_sleep_seconds(attempt))
                        continue
                    _write_deepseek_trace(
                        payload=payload,
                        response=data,
                        cache_path=cache_path,
                        event="api_response_hard_timeout_guard",
                        latency_seconds=time.perf_counter() - started,
                    )
                    return data
                else:
                    with _total_timeout_guard(_total_timeout_seconds()):
                        with _urlopen_no_system_proxy(req, timeout=self.timeout) as resp:
                            data = json.loads(resp.read().decode("utf-8"))
                    content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                    if not isinstance(content, str) or not content.strip():
                        last_error = DeepSeekClientError("DeepSeek returned empty message content")
                        if attempt >= self.max_retries:
                            raise last_error
                        time.sleep(self._retry_sleep_seconds(attempt))
                        continue
                    if cache_path is not None:
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        cache_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                    _write_deepseek_trace(
                        payload=payload,
                        response=data,
                        cache_path=cache_path,
                        event="api_response",
                        latency_seconds=time.perf_counter() - started,
                    )
                    return data
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace")
                # Retry transient API/server/rate-limit errors only.
                if exc.code not in {408, 409, 425, 429, 500, 502, 503, 504} or attempt >= self.max_retries:
                    error = f"DeepSeek HTTP {exc.code}: {detail}"
                    _write_deepseek_trace(
                        payload=payload,
                        response=None,
                        cache_path=cache_path,
                        event="api_error",
                        latency_seconds=time.perf_counter() - started,
                        error=error,
                    )
                    raise DeepSeekClientError(error) from exc
                last_error = DeepSeekClientError(f"DeepSeek HTTP {exc.code}: {detail}")
            except (urllib.error.URLError, TimeoutError, socket.timeout) as exc:
                if attempt >= self.max_retries:
                    error = f"DeepSeek request failed after {attempt + 1} attempts: {exc}"
                    _write_deepseek_trace(
                        payload=payload,
                        response=None,
                        cache_path=cache_path,
                        event="api_error",
                        latency_seconds=time.perf_counter() - started,
                        error=error,
                    )
                    raise DeepSeekClientError(error) from exc
                last_error = exc
            time.sleep(self._retry_sleep_seconds(attempt))
        error = f"DeepSeek request failed: {last_error}"
        _write_deepseek_trace(
            payload=payload,
            response=None,
            cache_path=cache_path,
            event="api_error",
            latency_seconds=time.perf_counter() - started,
            error=error,
        )
        raise DeepSeekClientError(error)

    def _retry_sleep_seconds(self, attempt: int) -> float:
        delay = self.retry_backoff * (2**attempt)
        return max(0.0, min(delay, self.retry_backoff_max))

    def _cache_path(self, payload: dict[str, Any]) -> Path | None:
        if os.getenv("DEEPSEEK_CACHE", "1") in {"0", "false", "False", "no"}:
            return None
        root = Path(os.getenv("DEEPSEEK_CACHE_DIR", "outputs/deepseek_cache"))
        stable = json.dumps({"base_url": self.base_url, "payload": payload}, ensure_ascii=False, sort_keys=True)
        key = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        return root / f"{key}.json"

    def debug_text(self, text: str, system: str | None = None) -> str:
        system = system or "You are an EVO² debugging assistant. Return concise actionable diagnostics."
        data = self.chat([
            {"role": "system", "content": system},
            {"role": "user", "content": text},
        ])
        return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def _total_timeout_seconds() -> float | None:
    raw = os.getenv("DEEPSEEK_TOTAL_TIMEOUT")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _hard_timeout_seconds() -> float | None:
    raw = os.getenv("DEEPSEEK_HARD_TIMEOUT")
    if not raw:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


def _resolve_max_retries(explicit_max_retries: int | None) -> int:
    if explicit_max_retries is not None:
        return max(0, int(explicit_max_retries))
    attempts = _resolve_int_env("DEEPSEEK_MAX_ATTEMPTS")
    if attempts is not None:
        return max(0, attempts - 1)
    retries = _resolve_int_env("DEEPSEEK_MAX_RETRIES")
    if retries is not None:
        return max(0, retries)
    return DEFAULT_DEEPSEEK_MAX_ATTEMPTS - 1


def _resolve_int_env(name: str) -> int | None:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _resolve_float_env(name: str, default: float, explicit_value: float | None = None) -> float:
    if explicit_value is not None:
        return float(explicit_value)
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _local_cache_hit_response(data: dict[str, Any], cache_path: Path) -> dict[str, Any]:
    """Return cached content while accounting actual API spend as zero.

    The cached file stores the provider response from the original miss, whose
    usage describes the original API call. Reusing it locally should not add to
    actual experiment token cost, but we keep the saved amount for diagnostics.
    """
    if not isinstance(data, dict):
        return data
    cached = json.loads(json.dumps(data, ensure_ascii=False))
    original_usage = cached.get("usage", {}) if isinstance(cached.get("usage"), dict) else {}
    details = original_usage.get("prompt_tokens_details", {}) if isinstance(original_usage.get("prompt_tokens_details"), dict) else {}
    provider_hit = int(original_usage.get("prompt_cache_hit_tokens", details.get("cached_tokens", 0)) or 0)
    provider_miss = int(original_usage.get("prompt_cache_miss_tokens", 0) or 0)
    if not provider_miss and original_usage.get("prompt_tokens") is not None:
        provider_miss = max(0, int(original_usage.get("prompt_tokens", 0) or 0) - provider_hit)
    cached["usage"] = {
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "total_tokens": 0,
        "local_cache_hits": 1,
        "local_cache_saved_prompt_tokens": int(original_usage.get("prompt_tokens", 0) or 0),
        "local_cache_saved_completion_tokens": int(original_usage.get("completion_tokens", 0) or 0),
        "local_cache_saved_tokens": int(original_usage.get("total_tokens", 0) or 0),
        "local_cache_provider_prompt_cache_hit_tokens": provider_hit,
        "local_cache_provider_prompt_cache_miss_tokens": provider_miss,
    }
    cached["evo2_cache"] = {"local_hit": True, "cache_path": str(cache_path)}
    return cached


def _cache_only_enabled() -> bool:
    return os.getenv("DEEPSEEK_CACHE_ONLY", "").strip().lower() in {"1", "true", "yes", "on"}


def _write_deepseek_trace(
    *,
    payload: dict[str, Any],
    response: dict[str, Any] | None,
    cache_path: Path | None,
    event: str,
    latency_seconds: float,
    error: str | None = None,
) -> None:
    trace_dir = os.getenv("DEEPSEEK_TRACE_DIR")
    if not trace_dir:
        return
    root = Path(trace_dir)
    root.mkdir(parents=True, exist_ok=True)
    stable = json.dumps({"base_url": os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1").rstrip("/"), "payload": payload}, ensure_ascii=False, sort_keys=True)
    cache_key = hashlib.sha256(stable.encode("utf-8")).hexdigest()
    record = {
        "timestamp_unix": time.time(),
        "event": event,
        "model": payload.get("model"),
        "cache_key": cache_key,
        "cache_path": str(cache_path) if cache_path is not None else None,
        "local_cache_hit": event == "local_cache_hit",
        "cache_only": _cache_only_enabled(),
        "latency_seconds": float(latency_seconds),
        "payload": payload,
        "response": response,
        "usage": (response or {}).get("usage", {}) if isinstance(response, dict) else {},
        "error": error,
    }
    trace_file = root / "deepseek_calls.jsonl"
    with trace_file.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def _use_system_proxy() -> bool:
    return os.getenv("DEEPSEEK_USE_SYSTEM_PROXY", "").strip().lower() in {"1", "true", "yes", "on"}


def _urlopen_no_system_proxy(req: urllib.request.Request, timeout: int):
    if _use_system_proxy():
        return urllib.request.urlopen(req, timeout=timeout)
    global _NO_PROXY_OPENER
    if _NO_PROXY_OPENER is None:
        with _NO_PROXY_OPENER_LOCK:
            if _NO_PROXY_OPENER is None:
                _NO_PROXY_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    return _NO_PROXY_OPENER.open(req, timeout=timeout)


def _chat_payload_hard_timeout(payload: dict[str, Any], base_url: str, api_key: str, timeout: int, hard_timeout: float, cache_path: str | None) -> dict[str, Any]:
    ctx = mp.get_context("fork")
    queue = ctx.Queue(maxsize=1)
    process = ctx.Process(target=_chat_payload_child, args=(payload, base_url, api_key, timeout, cache_path, queue))
    process.start()
    process.join(hard_timeout)
    if process.is_alive():
        process.terminate()
        process.join(2)
        raise TimeoutError(f"DeepSeek hard request timeout after {hard_timeout:.1f}s")
    if queue.empty():
        raise DeepSeekClientError(f"DeepSeek child process exited with code {process.exitcode}")
    status, value = queue.get()
    if status == "ok":
        return value
    raise DeepSeekClientError(value)


def _chat_payload_child(payload: dict[str, Any], base_url: str, api_key: str, timeout: int, cache_path: str | None, queue: Any) -> None:
    try:
        req = urllib.request.Request(
            f"{base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with _urlopen_no_system_proxy(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not isinstance(content, str) or not content.strip():
            raise DeepSeekClientError("DeepSeek returned empty message content")
        if cache_path is not None:
            p = Path(cache_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        queue.put(("ok", data))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        queue.put(("error", f"DeepSeek HTTP {exc.code}: {detail}"))
    except Exception as exc:
        queue.put(("error", repr(exc)))


class _total_timeout_guard:
    def __init__(self, seconds: float | None):
        self.seconds = seconds
        self.previous_handler = None
        self.previous_timer = None
        self.enabled = bool(seconds) and threading.current_thread() is threading.main_thread()

    def __enter__(self):
        if not self.enabled:
            return self
        self.previous_handler = signal.getsignal(signal.SIGALRM)
        self.previous_timer = signal.getitimer(signal.ITIMER_REAL)

        def raise_timeout(signum, frame):
            raise TimeoutError(f"DeepSeek total request timeout after {self.seconds:.1f}s")

        signal.signal(signal.SIGALRM, raise_timeout)
        signal.setitimer(signal.ITIMER_REAL, float(self.seconds))
        return self

    def __exit__(self, exc_type, exc, tb):
        if not self.enabled:
            return False
        signal.setitimer(signal.ITIMER_REAL, 0)
        if self.previous_handler is not None:
            signal.signal(signal.SIGALRM, self.previous_handler)
        if self.previous_timer and self.previous_timer[0] > 0:
            signal.setitimer(signal.ITIMER_REAL, *self.previous_timer)
        return False
