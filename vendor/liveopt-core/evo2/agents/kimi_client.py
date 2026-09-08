from __future__ import annotations

import hashlib
import http.client
import json
import os
import socket
import sys
import threading
import time
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from evo2.agents.deepseek_client import load_dotenv


DEFAULT_KIMI_BASE_URL = "https://api.kimi.com/coding/v1"
DEFAULT_KIMI_MODEL = "k3[1m]"


def _is_reasoning_family(model: Any) -> bool:
    """Model families that require temperature=1 and reasoning-token budgets (K2/K3)."""
    return str(model or "").lower().startswith(("k2", "k3"))
DEFAULT_KIMI_CONTEXT_WINDOW = 1_048_576
DEFAULT_KIMI_MIN_GENERATION_TOKENS = 32_000
DEFAULT_KIMI_MAX_GENERATION_TOKENS = 98_304
DEFAULT_KIMI_AGENT_IDENTITY = "LiveOpt-Coding-Agent"
DEFAULT_KIMI_AGENT_VERSION = "0.1.0"
_TRANSIENT_HTTP_CODES = {408, 409, 425, 429, 500, 502, 503, 504}
_NO_PROXY_OPENER: urllib.request.OpenerDirector | None = None
_NO_PROXY_OPENER_LOCK = threading.Lock()


class KimiK3ClientError(RuntimeError):
    """Raised when a Kimi Coding API request cannot be completed."""

    def __init__(self, message: str, *, status: int | None = None, detail: str = ""):
        super().__init__(message)
        self.status = status
        self.detail = detail


class KimiGenerationLimitError(KimiK3ClientError):
    """A completed K3 response that spent its full budget before the answer."""

    non_retryable = True

    def __init__(
        self,
        message: str,
        *,
        usage: dict[str, Any] | None = None,
        response: dict[str, Any] | None = None,
    ):
        super().__init__(message)
        self.usage = dict(usage or {})
        self.response = dict(response or {})


class KimiTransportError(KimiK3ClientError):
    """A provider/network interruption that must not count as solver failure."""

    infrastructure_limited = True
    resumable = True
    provider = "kimi"

    def __init__(
        self,
        message: str,
        *,
        detail: str = "",
        stream_stats: dict[str, Any] | None = None,
    ):
        super().__init__(message, detail=detail)
        self.stream_stats = dict(stream_stats or {})


class KimiQuotaLimitError(KimiK3ClientError):
    """A non-retryable account/window limit that should pause experiments."""

    quota_limited = True
    provider = "kimi"

    def __init__(
        self,
        message: str,
        *,
        status: int,
        detail: str,
        limit_scope: str,
        retry_after: str | None = None,
    ):
        super().__init__(message, status=status, detail=detail)
        self.limit_scope = limit_scope
        self.retry_after = retry_after

    def to_record(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "limit_scope": self.limit_scope,
            "http_status": self.status,
            "retry_after": self.retry_after,
            "message": str(self),
            "resumable": True,
        }


class KimiK3Client:
    """OpenAI-compatible client for Kimi K3 in a real coding agent.

    The Kimi Coding endpoint checks the calling tool's identity.  This client
    therefore sends a stable, truthful coding-agent identity in ``User-Agent``
    and companion diagnostic headers.  Override the identity only when this
    repository is embedded in a differently named *actual* client; do not use
    it to impersonate another coding product.

    Configuration is read from ``.env.local`` or the process environment:

    - ``KIMI_API_KEY`` (required)
    - ``KIMI_MODEL`` (default: ``k3[1m]``)
    - ``KIMI_BASE_URL`` (default: Kimi's OpenAI-compatible coding endpoint)
    - ``KIMI_CONTEXT_WINDOW`` (default: 1048576; local capability metadata)
    - ``KIMI_MIN_GENERATION_TOKENS`` (default: 32000; K3 reasoning and answer share ``max_tokens``)
    - ``KIMI_MAX_GENERATION_TOKENS`` (default: 98304; ceiling for adaptive truncation retries)
    - ``KIMI_AGENT_IDENTITY`` and ``KIMI_AGENT_VERSION``
    - ``KIMI_USER_AGENT`` (optional complete truthful User-Agent override)
    - ``KIMI_REASONING_EFFORT`` (default: ``medium``)
    - ``KIMI_STREAM`` (default: enabled; OpenAI-compatible SSE)
    - ``KIMI_STREAM_PROGRESS`` (default: disabled; prints metadata, never reasoning text)
    - ``KIMI_USE_SYSTEM_PROXY`` (default: disabled; direct connection)
    """

    provider = "kimi"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
        context_window: int | None = None,
        agent_identity: str | None = None,
        agent_version: str | None = None,
        user_agent: str | None = None,
        reasoning_effort: str | None = None,
        min_generation_tokens: int | None = None,
        max_generation_tokens: int | None = None,
        stream: bool | None = None,
        stream_progress: bool | None = None,
    ):
        load_dotenv()
        self.model = model or os.getenv("KIMI_MODEL", DEFAULT_KIMI_MODEL)
        raw_api_key = api_key or os.getenv("KIMI_API_KEY")
        self.api_key = _normalize_api_key(raw_api_key) if raw_api_key else None
        self.base_url = (base_url or os.getenv("KIMI_BASE_URL", DEFAULT_KIMI_BASE_URL)).rstrip("/")
        self.timeout = int(timeout or os.getenv("KIMI_TIMEOUT", "360"))
        self.max_retries = int(
            max_retries if max_retries is not None else os.getenv("KIMI_MAX_RETRIES", "2")
        )
        self.retry_backoff = float(
            retry_backoff if retry_backoff is not None else os.getenv("KIMI_RETRY_BACKOFF", "2")
        )
        self.retry_backoff_max = float(os.getenv("KIMI_RETRY_BACKOFF_MAX", "30"))
        self.context_window = int(
            context_window
            if context_window is not None
            else os.getenv("KIMI_CONTEXT_WINDOW", str(DEFAULT_KIMI_CONTEXT_WINDOW))
        )
        self.agent_identity = agent_identity or os.getenv(
            "KIMI_AGENT_IDENTITY", DEFAULT_KIMI_AGENT_IDENTITY
        )
        self.agent_version = agent_version or os.getenv(
            "KIMI_AGENT_VERSION", DEFAULT_KIMI_AGENT_VERSION
        )
        self.user_agent = user_agent or os.getenv(
            "KIMI_USER_AGENT", f"{self.agent_identity}/{self.agent_version}"
        )
        self.reasoning_effort = reasoning_effort or os.getenv(
            "KIMI_REASONING_EFFORT", "medium"
        )
        self.stream = _env_flag("KIMI_STREAM", default=True) if stream is None else bool(stream)
        self.stream_progress = (
            _env_flag("KIMI_STREAM_PROGRESS", default=False)
            if stream_progress is None
            else bool(stream_progress)
        )
        self.stream_include_usage = _env_flag(
            "KIMI_STREAM_INCLUDE_USAGE", default=True
        )
        self.min_generation_tokens = int(
            min_generation_tokens
            if min_generation_tokens is not None
            else os.getenv(
                "KIMI_MIN_GENERATION_TOKENS",
                str(DEFAULT_KIMI_MIN_GENERATION_TOKENS),
            )
        )
        self.max_generation_tokens = int(
            max_generation_tokens
            if max_generation_tokens is not None
            else os.getenv(
                "KIMI_MAX_GENERATION_TOKENS",
                str(DEFAULT_KIMI_MAX_GENERATION_TOKENS),
            )
        )
        self.last_payload: dict[str, Any] = {}
        self.last_request_headers: dict[str, str] = {}
        self.last_stream_stats: dict[str, Any] = {}

        if not self.api_key:
            raise KimiK3ClientError(
                "KIMI_API_KEY is not set. Export a newly generated key or put it in the "
                "git-ignored .env.local file."
            )
        if self.max_retries < 0:
            raise ValueError("KIMI_MAX_RETRIES must be non-negative")
        if self.context_window <= 0:
            raise ValueError("KIMI_CONTEXT_WINDOW must be positive")
        if self.min_generation_tokens <= 0:
            raise ValueError("KIMI_MIN_GENERATION_TOKENS must be positive")
        if self.max_generation_tokens < self.min_generation_tokens:
            raise ValueError(
                "KIMI_MAX_GENERATION_TOKENS must be at least KIMI_MIN_GENERATION_TOKENS"
            )
        for name, value in (
            ("KIMI_AGENT_IDENTITY", self.agent_identity),
            ("KIMI_AGENT_VERSION", self.agent_version),
            ("KIMI_USER_AGENT", self.user_agent),
        ):
            _validate_header_value(name, value)

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 4096,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        is_k3 = _is_reasoning_family(self.model)
        requested_max_tokens = int(max_tokens) if max_tokens and max_tokens > 0 else 0
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            # K3 currently accepts temperature=1 only.  Keep the common client
            # signature while normalizing this provider-specific constraint.
            "temperature": 1.0 if is_k3 else temperature,
        }
        if requested_max_tokens:
            # K3 counts hidden reasoning and the visible answer against the
            # same max_tokens ceiling. Small code/JSON caps can therefore end
            # with an empty or one-line answer after the reasoning consumes
            # the budget. Other providers and models keep the caller's cap.
            payload["max_tokens"] = (
                max(requested_max_tokens, self.min_generation_tokens)
                if is_k3 and self.reasoning_effort
                else requested_max_tokens
            )
        if is_k3 and self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        self.last_payload = dict(payload)

        try:
            return self._chat_payload(payload)
        except KimiK3ClientError as exc:
            # Some compatible gateways do not implement response_format.  The
            # agent prompts already require strict JSON, so one format-only
            # fallback keeps the integration portable without changing intent.
            if (
                json_mode
                and exc.status == 400
                and "response_format" in (exc.detail or str(exc)).lower()
            ):
                payload = dict(payload)
                payload.pop("response_format", None)
                self.last_payload = dict(payload)
                return self._chat_payload(payload)
            raise

    def identity_headers(self) -> dict[str, str]:
        """Return the non-secret headers that identify the actual agent."""

        return {
            "User-Agent": self.user_agent,
            "X-Client-Name": self.agent_identity,
            "X-Client-Version": self.agent_version,
            "X-Client-Type": "coding-agent",
        }

    def debug_config(self) -> dict[str, Any]:
        """Return safe connection metadata suitable for smoke-test output."""

        return {
            "provider": self.provider,
            "base_url": self.base_url,
            "model": self.model,
            "context_window": self.context_window,
            "reasoning_effort": self.reasoning_effort,
            "stream": self.stream,
            "stream_progress": self.stream_progress,
            "stream_include_usage": self.stream_include_usage,
            "use_system_proxy": _use_system_proxy(),
            "min_generation_tokens": self.min_generation_tokens,
            "max_generation_tokens": self.max_generation_tokens,
            "agent_identity": self.agent_identity,
            "agent_version": self.agent_version,
            "user_agent": self.user_agent,
            "api_key_configured": bool(self.api_key),
        }

    def _chat_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        started = time.perf_counter()
        cached = self._load_compatible_cache(payload, started)
        if cached is not None:
            return cached
        cache_path = self._cache_path(payload)
        if _env_flag("KIMI_CACHE_ONLY", default=False):
            raise KimiK3ClientError(
                "KIMI_CACHE_ONLY is enabled and the local Kimi response cache missed."
            )

        last_error: Exception | None = None
        generation_attempt_usages: list[dict[str, Any]] = []
        for attempt in range(self.max_retries + 1):
            wire_payload = dict(payload)
            if self.stream:
                # Keep this transport-only field out of the cache identity so
                # complete responses produced before streaming was enabled are
                # still reusable for exactly the same logical request.
                wire_payload["stream"] = True
                if self.stream_include_usage:
                    wire_payload["stream_options"] = {"include_usage": True}
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream" if self.stream else "application/json",
                **self.identity_headers(),
            }
            self.last_request_headers = {
                key: ("Bearer <redacted>" if key.lower() == "authorization" else value)
                for key, value in headers.items()
            }
            request = urllib.request.Request(
                f"{self.base_url}/chat/completions",
                data=json.dumps(wire_payload, ensure_ascii=False).encode("utf-8"),
                headers=headers,
                method="POST",
            )
            try:
                stream_stats = _new_stream_stats(enabled=self.stream, attempt=attempt + 1)
                self.last_stream_stats = stream_stats
                attempt_started = time.perf_counter()
                with _urlopen_no_system_proxy(request, timeout=self.timeout) as response:
                    stream_stats["response_headers_seconds"] = (
                        time.perf_counter() - attempt_started
                    )
                    data = _read_kimi_response(
                        response,
                        expect_stream=self.stream,
                        stats=stream_stats,
                        show_progress=self.stream_progress,
                    )
                stream_stats["completed"] = True
                self.last_stream_stats = _public_stream_stats(stream_stats)
                if _response_was_truncated(data):
                    generation_attempt_usages.append(
                        dict(data.get("usage") or {}) if isinstance(data, dict) else {}
                    )
                    current = KimiGenerationLimitError(
                        "Kimi response exhausted max_tokens before completing the visible answer",
                        usage=_sum_provider_usages(generation_attempt_usages),
                        response=data if isinstance(data, dict) else {},
                    )
                    self._trace(
                        "api_response_truncated",
                        payload,
                        data,
                        started,
                        error=str(current),
                        stream_stats=self.last_stream_stats,
                    )
                    expanded = self._expanded_generation_payload(payload)
                    if expanded is None or attempt >= self.max_retries:
                        raise current
                    last_error = current
                    payload = expanded
                    self.last_payload = dict(payload)
                    cache_path = self._cache_path(payload)
                    cached = self._load_compatible_cache(payload, started)
                    if cached is not None:
                        return cached
                    time.sleep(min(self.retry_backoff * (2**attempt), self.retry_backoff_max))
                    continue
                generation_attempt_usages.append(
                    dict(data.get("usage") or {}) if isinstance(data, dict) else {}
                )
                if len(generation_attempt_usages) > 1:
                    data["final_attempt_usage"] = dict(data.get("usage") or {})
                    data["generation_attempt_usages"] = [
                        dict(usage) for usage in generation_attempt_usages
                    ]
                    data["usage"] = _sum_provider_usages(generation_attempt_usages)
                content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not isinstance(content, str) or not content.strip():
                    raise KimiK3ClientError("Kimi returned empty message content")
                if cache_path is not None:
                    _atomic_write_json(cache_path, data)
                self._trace(
                    "api_response",
                    payload,
                    data,
                    started,
                    cache_path=cache_path,
                    stream_stats=self.last_stream_stats,
                )
                return data
            except urllib.error.HTTPError as exc:
                detail = _safe_error_detail(exc.read().decode("utf-8", errors="replace"), self.api_key)
                retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
                current = _http_error(
                    exc.code,
                    detail,
                    self.user_agent,
                    retry_after=retry_after,
                )
                if isinstance(current, KimiQuotaLimitError):
                    self._trace(
                        "quota_limited",
                        payload,
                        None,
                        started,
                        error=str(current),
                        quota_limit=current.to_record(),
                        stream_stats=self.last_stream_stats,
                    )
                    raise current from exc
                if exc.code not in _TRANSIENT_HTTP_CODES:
                    self._trace(
                        "api_error",
                        payload,
                        None,
                        started,
                        error=str(current),
                        stream_stats=_public_stream_stats(self.last_stream_stats),
                    )
                    raise current from exc
                if attempt >= self.max_retries:
                    transport = KimiTransportError(
                        f"Kimi transient HTTP {exc.code} persisted after {attempt + 1} attempts",
                        detail=detail,
                        stream_stats=_public_stream_stats(self.last_stream_stats),
                    )
                    self._trace(
                        "api_transport_error",
                        payload,
                        None,
                        started,
                        error=str(transport),
                        stream_stats=transport.stream_stats,
                    )
                    raise transport from exc
                last_error = current
            except (
                urllib.error.URLError,
                TimeoutError,
                socket.timeout,
                http.client.RemoteDisconnected,
                http.client.IncompleteRead,
                ConnectionResetError,
                BrokenPipeError,
            ) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    current = KimiTransportError(
                        f"Kimi transport failed after {attempt + 1} attempts: {exc}",
                        detail=f"{type(exc).__name__}: {exc}",
                        stream_stats=_public_stream_stats(self.last_stream_stats),
                    )
                    self._trace(
                        "api_transport_error",
                        payload,
                        None,
                        started,
                        error=str(current),
                        stream_stats=current.stream_stats,
                    )
                    raise current from exc
            except json.JSONDecodeError as exc:
                current = KimiK3ClientError(f"Kimi returned invalid JSON: {exc}")
                self._trace(
                    "api_error",
                    payload,
                    None,
                    started,
                    error=str(current),
                    stream_stats=_public_stream_stats(self.last_stream_stats),
                )
                raise current from exc
            except KimiK3ClientError as exc:
                if isinstance(exc, KimiQuotaLimitError):
                    self._trace(
                        "quota_limited",
                        payload,
                        None,
                        started,
                        error=str(exc),
                        quota_limit=exc.to_record(),
                        stream_stats=_public_stream_stats(self.last_stream_stats),
                    )
                    raise
                if isinstance(exc, KimiTransportError):
                    streamed = int(
                        (exc.stream_stats or self.last_stream_stats).get(
                            "data_event_count", 0
                        )
                        or 0
                    )
                    # Once the provider has emitted model tokens, an automatic
                    # retry can spend the same paid request twice. Checkpoint
                    # the trajectory and let the experiment resume explicitly.
                    if streamed > 0 or attempt >= self.max_retries:
                        self._trace(
                            "api_transport_error",
                            payload,
                            None,
                            started,
                            error=str(exc),
                            stream_stats=exc.stream_stats,
                        )
                        raise
                    last_error = exc
                    time.sleep(
                        min(
                            self.retry_backoff * (2**attempt),
                            self.retry_backoff_max,
                        )
                    )
                    continue
                if getattr(exc, "non_retryable", False):
                    self._trace(
                        "api_error",
                        payload,
                        None,
                        started,
                        error=str(exc),
                        stream_stats=_public_stream_stats(self.last_stream_stats),
                    )
                    raise
                if attempt >= self.max_retries:
                    self._trace(
                        "api_error",
                        payload,
                        None,
                        started,
                        error=str(exc),
                        stream_stats=_public_stream_stats(self.last_stream_stats),
                    )
                    raise
                last_error = exc
            time.sleep(min(self.retry_backoff * (2**attempt), self.retry_backoff_max))

        raise KimiK3ClientError(f"Kimi request failed: {last_error}")

    def _expanded_generation_payload(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        if not _is_reasoning_family(payload.get("model")):
            return None
        current = int(payload.get("max_tokens") or self.min_generation_tokens)
        if current >= self.max_generation_tokens:
            return None
        expanded = dict(payload)
        expanded["max_tokens"] = min(self.max_generation_tokens, max(current + 1, current * 2))
        return expanded

    def _load_compatible_cache(
        self,
        payload: dict[str, Any],
        started: float,
    ) -> dict[str, Any] | None:
        """Reuse a lower-cap response only when it explicitly finished.

        Raising K3's cap must not invalidate a complete cached answer from the
        same prompt. Truncated lower-cap entries are logged and skipped.
        """

        for candidate in _compatible_cache_payloads(payload):
            cache_path = self._cache_path(candidate)
            if cache_path is None or not cache_path.exists():
                continue
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            if _response_was_truncated(data):
                self._trace(
                    "local_cache_truncated",
                    candidate,
                    data,
                    started,
                    cache_path=cache_path,
                    error="cached Kimi response ended with finish_reason=length",
                )
                continue
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            if not isinstance(content, str) or not content.strip():
                continue
            self._trace("local_cache_hit", candidate, data, started, cache_path=cache_path)
            return data
        return None

    def _cache_path(self, payload: dict[str, Any]) -> Path | None:
        if not _env_flag("KIMI_CACHE", default=True):
            return None
        stable = json.dumps(
            {
                "base_url": self.base_url,
                "agent_identity": self.agent_identity,
                "payload": payload,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        digest = hashlib.sha256(stable.encode("utf-8")).hexdigest()
        root = Path(os.getenv("KIMI_CACHE_DIR", "outputs/kimi_cache"))
        return root / f"{digest}.json"

    def _trace(
        self,
        event: str,
        payload: dict[str, Any],
        response: dict[str, Any] | None,
        started: float,
        *,
        cache_path: Path | None = None,
        error: str = "",
        quota_limit: dict[str, Any] | None = None,
        stream_stats: dict[str, Any] | None = None,
    ) -> None:
        trace_dir = os.getenv("KIMI_TRACE_DIR")
        if not trace_dir:
            return
        record = {
            "event": event,
            "timestamp": time.time(),
            "latency_seconds": time.perf_counter() - started,
            "provider": self.provider,
            "base_url": self.base_url,
            "model": payload.get("model"),
            "request_max_tokens": payload.get("max_tokens"),
            "finish_reason": (
                ((response or {}).get("choices") or [{}])[0].get("finish_reason", "")
                if isinstance(((response or {}).get("choices") or [{}])[0], dict)
                else ""
            ),
            "agent_identity": self.agent_identity,
            "user_agent": self.user_agent,
            "cache_path": str(cache_path) if cache_path is not None else "",
            "usage": (response or {}).get("usage", {}),
            "error": error,
            "quota_limit": quota_limit or {},
            "stream": _public_stream_stats(stream_stats or {}),
        }
        path = Path(trace_dir) / "kimi_calls.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")


def _new_stream_stats(*, enabled: bool, attempt: int) -> dict[str, Any]:
    now = time.perf_counter()
    return {
        "enabled": bool(enabled),
        "attempt": int(attempt),
        "response_mode": "pending",
        "response_content_type": "",
        "response_headers_seconds": None,
        "first_event_seconds": None,
        "first_data_seconds": None,
        "last_event_seconds": None,
        "max_inter_event_gap_seconds": 0.0,
        "line_count": 0,
        "event_count": 0,
        "data_event_count": 0,
        "heartbeat_count": 0,
        "content_delta_events": 0,
        "reasoning_delta_events": 0,
        "content_chars": 0,
        "reasoning_chars": 0,
        "wire_bytes": 0,
        "done_seen": False,
        "finish_reason": "",
        "completed": False,
        "_started_monotonic": now,
        "_last_event_monotonic": None,
        "_last_progress_monotonic": now,
    }


def _public_stream_stats(stats: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(stats, dict):
        return {}
    public: dict[str, Any] = {}
    for key, value in stats.items():
        if str(key).startswith("_"):
            continue
        if isinstance(value, float):
            public[key] = round(value, 6)
        else:
            public[key] = value
    return public


def _read_kimi_response(
    response: Any,
    *,
    expect_stream: bool,
    stats: dict[str, Any],
    show_progress: bool,
) -> dict[str, Any]:
    content_type = _response_content_type(response)
    stats["response_content_type"] = content_type
    is_sse = expect_stream and "text/event-stream" in content_type.lower()
    if not is_sse:
        stats["response_mode"] = "json"
        raw = response.read()
        stats["wire_bytes"] = len(raw)
        return json.loads(raw.decode("utf-8"))

    stats["response_mode"] = "sse"
    chunks: list[dict[str, Any]] = []
    pending_data: list[str] = []

    def consume_event() -> None:
        if not pending_data:
            return
        payload_text = "\n".join(pending_data).strip()
        pending_data.clear()
        if not payload_text:
            return
        _mark_stream_event(stats, data=True)
        if payload_text == "[DONE]":
            stats["done_seen"] = True
            _report_stream_progress(stats, show_progress=show_progress, force=True)
            return
        try:
            chunk = json.loads(payload_text)
        except json.JSONDecodeError as exc:
            raise KimiTransportError(
                f"Kimi returned a malformed SSE data event: {exc}",
                detail=payload_text[:1000],
                stream_stats=_public_stream_stats(stats),
            ) from exc
        if isinstance(chunk, dict) and chunk.get("error"):
            raise _stream_error(chunk["error"])
        if not isinstance(chunk, dict):
            raise KimiTransportError(
                "Kimi returned a non-object SSE data event",
                detail=payload_text[:1000],
                stream_stats=_public_stream_stats(stats),
            )
        chunks.append(chunk)
        _update_delta_stats(stats, chunk)
        _report_stream_progress(stats, show_progress=show_progress)

    try:
        while True:
            raw_line = response.readline()
            if not raw_line:
                break
            stats["wire_bytes"] += len(raw_line)
            stats["line_count"] += 1
            line = raw_line.decode("utf-8", errors="replace").rstrip("\r\n")
            if not line:
                consume_event()
                continue
            if line.startswith(":"):
                stats["heartbeat_count"] += 1
                _mark_stream_event(stats, data=False)
                _report_stream_progress(stats, show_progress=show_progress)
                continue
            if line.startswith("data:"):
                pending_data.append(line[5:].lstrip())
        consume_event()
    except KimiK3ClientError:
        raise
    except Exception as exc:
        raise KimiTransportError(
            f"Kimi SSE stream was interrupted: {type(exc).__name__}: {exc}",
            detail=f"{type(exc).__name__}: {exc}",
            stream_stats=_public_stream_stats(stats),
        ) from exc

    data = _assemble_stream_chunks(chunks)
    choices = data.get("choices") if isinstance(data, dict) else None
    first_choice = choices[0] if isinstance(choices, list) and choices else {}
    finish_reason = str(first_choice.get("finish_reason") or "")
    stats["finish_reason"] = finish_reason
    if not stats.get("done_seen") and not finish_reason:
        raise KimiTransportError(
            "Kimi SSE connection ended before [DONE] or a finish_reason",
            detail="incomplete SSE response",
            stream_stats=_public_stream_stats(stats),
        )
    return data


def _response_content_type(response: Any) -> str:
    headers = getattr(response, "headers", None)
    if headers is None:
        return ""
    try:
        return str(headers.get("Content-Type") or "")
    except (AttributeError, TypeError):
        return ""


def _mark_stream_event(stats: dict[str, Any], *, data: bool) -> None:
    now = time.perf_counter()
    started = float(stats.get("_started_monotonic") or now)
    previous = stats.get("_last_event_monotonic")
    elapsed = now - started
    stats["event_count"] += 1
    if data:
        stats["data_event_count"] += 1
        if stats.get("first_data_seconds") is None:
            stats["first_data_seconds"] = elapsed
    if stats.get("first_event_seconds") is None:
        stats["first_event_seconds"] = elapsed
    if isinstance(previous, (float, int)):
        stats["max_inter_event_gap_seconds"] = max(
            float(stats.get("max_inter_event_gap_seconds") or 0.0), now - float(previous)
        )
    stats["last_event_seconds"] = elapsed
    stats["_last_event_monotonic"] = now


def _update_delta_stats(stats: dict[str, Any], chunk: dict[str, Any]) -> None:
    for choice in chunk.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        delta = choice.get("delta")
        if not isinstance(delta, dict):
            delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
        content = _text_delta(delta.get("content"))
        reasoning = _text_delta(delta.get("reasoning_content"))
        if content:
            stats["content_delta_events"] += 1
            stats["content_chars"] += len(content)
        if reasoning:
            stats["reasoning_delta_events"] += 1
            stats["reasoning_chars"] += len(reasoning)


def _report_stream_progress(
    stats: dict[str, Any], *, show_progress: bool, force: bool = False
) -> None:
    if not show_progress:
        return
    now = time.perf_counter()
    last = float(stats.get("_last_progress_monotonic") or 0.0)
    interval = float(os.getenv("KIMI_STREAM_PROGRESS_INTERVAL", "5") or 5)
    first = int(stats.get("data_event_count") or 0) == 1
    if not (force or first or now - last >= max(0.1, interval)):
        return
    stats["_last_progress_monotonic"] = now
    record = {
        "event": "kimi_stream_progress",
        "elapsed_seconds": round(
            now - float(stats.get("_started_monotonic") or now), 3
        ),
        "data_events": int(stats.get("data_event_count") or 0),
        "reasoning_chars": int(stats.get("reasoning_chars") or 0),
        "content_chars": int(stats.get("content_chars") or 0),
        "max_gap_seconds": round(
            float(stats.get("max_inter_event_gap_seconds") or 0.0), 3
        ),
        "done": bool(stats.get("done_seen")),
    }
    print(json.dumps(record, ensure_ascii=False), file=sys.stderr, flush=True)


def _assemble_stream_chunks(chunks: list[dict[str, Any]]) -> dict[str, Any]:
    response: dict[str, Any] = {"object": "chat.completion", "choices": []}
    states: dict[int, dict[str, Any]] = {}
    for chunk in chunks:
        for key in ("id", "created", "model", "system_fingerprint"):
            if chunk.get(key) is not None:
                response[key] = chunk[key]
        if isinstance(chunk.get("usage"), dict):
            response["usage"] = dict(chunk["usage"])
        for choice in chunk.get("choices") or []:
            if not isinstance(choice, dict):
                continue
            index = int(choice.get("index") or 0)
            state = states.setdefault(
                index,
                {
                    "index": index,
                    "role": "assistant",
                    "content": [],
                    "reasoning_content": [],
                    "tool_calls": {},
                    "finish_reason": None,
                },
            )
            delta = choice.get("delta")
            if not isinstance(delta, dict):
                delta = choice.get("message") if isinstance(choice.get("message"), dict) else {}
            if delta.get("role"):
                state["role"] = str(delta["role"])
            content = _text_delta(delta.get("content"))
            reasoning = _text_delta(delta.get("reasoning_content"))
            if content:
                state["content"].append(content)
            if reasoning:
                state["reasoning_content"].append(reasoning)
            _merge_tool_call_deltas(state["tool_calls"], delta.get("tool_calls"))
            if choice.get("finish_reason") is not None:
                state["finish_reason"] = choice.get("finish_reason")

    choices: list[dict[str, Any]] = []
    for index in sorted(states):
        state = states[index]
        message: dict[str, Any] = {
            "role": state["role"],
            "content": "".join(state["content"]),
        }
        reasoning = "".join(state["reasoning_content"])
        if reasoning:
            message["reasoning_content"] = reasoning
        if state["tool_calls"]:
            message["tool_calls"] = [
                state["tool_calls"][key] for key in sorted(state["tool_calls"])
            ]
        choices.append(
            {
                "index": index,
                "message": message,
                "finish_reason": state["finish_reason"],
            }
        )
    response["choices"] = choices
    response.setdefault("usage", {})
    return response


def _text_delta(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for item in value:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)
    return ""


def _merge_tool_call_deltas(target: dict[int, dict[str, Any]], raw: Any) -> None:
    if not isinstance(raw, list):
        return
    for position, delta in enumerate(raw):
        if not isinstance(delta, dict):
            continue
        index = int(delta.get("index") if delta.get("index") is not None else position)
        current = target.setdefault(
            index,
            {"index": index, "id": "", "type": "function", "function": {"name": "", "arguments": ""}},
        )
        for key in ("id", "type"):
            if delta.get(key):
                current[key] = str(delta[key])
        function = delta.get("function") if isinstance(delta.get("function"), dict) else {}
        if function.get("name"):
            current["function"]["name"] += str(function["name"])
        if function.get("arguments"):
            current["function"]["arguments"] += str(function["arguments"])


def _stream_error(raw: Any) -> KimiK3ClientError:
    error = raw if isinstance(raw, dict) else {"message": str(raw)}
    detail = json.dumps(error, ensure_ascii=False)[:4000]
    raw_status = error.get("status") or error.get("status_code") or error.get("code")
    try:
        status = int(raw_status)
    except (TypeError, ValueError):
        status = 429 if "usage limit" in detail.lower() else 500
    return _http_error(status, detail, DEFAULT_KIMI_AGENT_IDENTITY)


def _response_was_truncated(response: dict[str, Any]) -> bool:
    choices = response.get("choices") if isinstance(response, dict) else None
    if not isinstance(choices, list) or not choices:
        return False
    first = choices[0] if isinstance(choices[0], dict) else {}
    return str(first.get("finish_reason") or "").strip().lower() == "length"


def _sum_provider_usages(usages: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum paid generation attempts while preserving provider detail fields."""

    result: dict[str, Any] = {}
    for usage in usages:
        if not isinstance(usage, dict):
            continue
        for key, value in usage.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                result[key] = int(result.get(key, 0) or 0) + int(value)
            elif isinstance(value, dict):
                current = result.setdefault(key, {})
                if not isinstance(current, dict):
                    continue
                for detail_key, detail_value in value.items():
                    if isinstance(detail_value, bool) or not isinstance(
                        detail_value, (int, float)
                    ):
                        continue
                    current[detail_key] = int(current.get(detail_key, 0) or 0) + int(
                        detail_value
                    )
    return result


def _compatible_cache_payloads(payload: dict[str, Any]) -> list[dict[str, Any]]:
    candidates = [dict(payload)]
    if not _is_reasoning_family(payload.get("model")):
        return candidates
    current = int(payload.get("max_tokens") or 0)
    # These are the historical caps used by LiveOpt's code and JSON calls.
    # A lower-cap answer is compatible only if _load_compatible_cache verifies
    # that it ended normally rather than with finish_reason=length.
    for budget in (24_000, 12_000, 8_000, 5_000, 4_096, 2_200, 1_200):
        if 0 < budget < current:
            candidate = dict(payload)
            candidate["max_tokens"] = budget
            candidates.append(candidate)
    return candidates


def _http_error(
    status: int,
    detail: str,
    user_agent: str,
    *,
    retry_after: str | None = None,
) -> KimiK3ClientError:
    limit_scope = _quota_limit_scope(status, detail)
    if limit_scope is not None:
        return KimiQuotaLimitError(
            (
                f"Kimi {limit_scope} quota is exhausted; the experiment was paused before "
                "making further provider calls."
            ),
            status=status,
            detail=detail,
            limit_scope=limit_scope,
            retry_after=retry_after,
        )
    hint = ""
    if status == 401:
        hint = " Check that the key was created in the Kimi Code console and that the plan permits this model."
    elif status == 403:
        hint = (
            f" The request declared the truthful coding-agent User-Agent {user_agent!r}; "
            "check Kimi Code membership, quota, and third-party-agent access."
        )
    return KimiK3ClientError(
        f"Kimi HTTP {status}: {detail}.{hint}",
        status=status,
        detail=detail,
    )


def _quota_limit_scope(status: int, detail: str) -> str | None:
    text = detail.lower()
    if "monthly usage limit" in text or ("monthly" in text and "usage limit" in text):
        return "monthly"
    if "usage limit for this billing cycle" in text:
        # Kimi's current error reference describes this 403 as the weekly
        # membership allowance, even though the wire text says billing cycle.
        return "weekly"
    if "weekly" in text and ("limit" in text or "quota" in text):
        return "weekly"
    if "usage limit for this period" in text:
        return "rolling_5h"
    if status in {403, 429} and "usage limit" in text:
        return "unknown_period"
    return None


def _safe_error_detail(detail: str, api_key: str | None) -> str:
    text = detail.strip()
    if api_key:
        text = text.replace(api_key, "<redacted>")
    return text[:4000]


def _use_system_proxy() -> bool:
    return _env_flag("KIMI_USE_SYSTEM_PROXY", default=False)


def _urlopen_no_system_proxy(request: urllib.request.Request, timeout: int):
    """Open Kimi directly unless the caller explicitly opts into shell proxies."""

    if _use_system_proxy():
        return urllib.request.urlopen(request, timeout=timeout)
    global _NO_PROXY_OPENER
    if _NO_PROXY_OPENER is None:
        with _NO_PROXY_OPENER_LOCK:
            if _NO_PROXY_OPENER is None:
                _NO_PROXY_OPENER = urllib.request.build_opener(
                    urllib.request.ProxyHandler({})
                )
    return _NO_PROXY_OPENER.open(request, timeout=timeout)


def _normalize_api_key(value: str) -> str:
    """Remove copy/paste format marks while never exposing the secret."""

    normalized = "".join(
        character for character in value.strip() if unicodedata.category(character) != "Cf"
    )
    try:
        normalized.encode("ascii")
    except UnicodeEncodeError as exc:
        raise KimiK3ClientError(
            "KIMI_API_KEY contains non-ASCII characters. Re-copy the key from the Kimi Code console."
        ) from exc
    if not normalized:
        raise KimiK3ClientError("KIMI_API_KEY is empty after removing copy/paste formatting characters.")
    return normalized


def _validate_header_value(name: str, value: str) -> None:
    if not value or "\r" in value or "\n" in value:
        raise ValueError(f"{name} must be a non-empty single-line HTTP header value")
    try:
        value.encode("latin-1")
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} must contain only HTTP header-safe characters") from exc


def _env_flag(name: str, *, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(f"{path.suffix}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    temporary.replace(path)
