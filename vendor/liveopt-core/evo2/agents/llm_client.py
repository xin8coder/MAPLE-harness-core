from __future__ import annotations

import os
from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ChatClient(Protocol):
    """Minimal interface shared by provider-backed LiveOpt agents."""

    model: str

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> dict[str, Any]: ...


def is_llm_quota_limit_error(exc: BaseException) -> bool:
    """Recognize a provider quota error, including a safely chained wrapper."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "quota_limited", False)):
            return True
        current = current.__cause__ or current.__context__
    return False


def llm_quota_limit_record(exc: BaseException) -> dict[str, Any]:
    """Extract non-secret quota metadata from an exception chain."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "quota_limited", False)):
            return {
                "provider": str(getattr(current, "provider", "unknown")),
                "limit_scope": str(getattr(current, "limit_scope", "unknown")),
                "http_status": getattr(current, "status", None),
                "retry_after": getattr(current, "retry_after", None),
                "message": str(current),
                "resumable": True,
            }
        current = current.__cause__ or current.__context__
    return {}


def is_llm_infrastructure_error(exc: BaseException) -> bool:
    """Recognize a resumable provider/network failure through wrapper chains."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "infrastructure_limited", False)):
            return True
        current = current.__cause__ or current.__context__
    return False


def llm_infrastructure_error_record(exc: BaseException) -> dict[str, Any]:
    """Extract safe transport metadata without treating it as model failure."""

    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if bool(getattr(current, "infrastructure_limited", False)):
            return {
                "provider": str(getattr(current, "provider", "unknown")),
                "message": str(current),
                "stream": dict(getattr(current, "stream_stats", {}) or {}),
                "resumable": True,
            }
        current = current.__cause__ or current.__context__
    return {}


def infer_llm_provider(model: str | None = None, provider: str | None = None) -> str:
    """Resolve a provider without changing the existing DeepSeek default."""

    explicit = (provider or os.getenv("LLM_PROVIDER", "")).strip().lower()
    aliases = {
        "deepseek": "deepseek",
        "kimi": "kimi",
        "kimi-code": "kimi",
        "moonshot": "kimi",
    }
    if explicit:
        if explicit not in aliases:
            raise ValueError(f"unsupported LLM provider: {explicit}")
        return aliases[explicit]

    normalized_model = (model or "").strip().lower()
    if normalized_model.startswith(("k2", "k3", "kimi-", "moonshot-")):
        return "kimi"
    return "deepseek"


def create_llm_client(
    model: str | None = None,
    *,
    provider: str | None = None,
    **kwargs: Any,
) -> ChatClient:
    """Create the provider client used by LiveOpt and its baseline agents."""

    resolved = infer_llm_provider(model=model, provider=provider)
    if resolved == "kimi":
        from evo2.agents.kimi_client import KimiK3Client

        return KimiK3Client(model=model, **kwargs)

    from evo2.agents.deepseek_client import DeepSeekDebugClient

    return DeepSeekDebugClient(model=model, **kwargs)


# Backward-compatible name for imports that treated this module as an interface.
LLMClient = ChatClient
