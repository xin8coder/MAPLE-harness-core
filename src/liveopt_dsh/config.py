"""Process-level configuration for the isolated LiveOpt MCP sidecar."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


CACHE_MODES = frozenset({"read_write", "cache_only", "off"})
NETWORK_MODES = frozenset({"auto", "direct", "system_proxy"})


@dataclass(frozen=True)
class ServiceConfig:
    state_dir: Path
    workspace_root: Path
    cache_mode: str = "read_write"
    network_mode: str = "auto"
    max_workers: int = 2
    max_result_archive: int = 50
    default_model: str = "deepseek-v4-flash"
    solver_time_limit_seconds: float = 30.0

    @classmethod
    def from_env(cls) -> "ServiceConfig":
        state_dir = Path(
            os.getenv("LIVEOPT_MCP_STATE_DIR", "~/.local/share/liveopt-dsh/state")
        ).expanduser()
        workspace_root = Path(
            os.getenv("LIVEOPT_MCP_WORKSPACE_ROOT", os.getcwd())
        ).expanduser()
        cache_mode = os.getenv("LIVEOPT_MCP_CACHE_MODE", "read_write").strip().lower()
        if cache_mode not in CACHE_MODES:
            raise ValueError(
                "LIVEOPT_MCP_CACHE_MODE must be one of: " + ", ".join(sorted(CACHE_MODES))
            )
        network_mode = os.getenv("LIVEOPT_MCP_NETWORK_MODE", "auto").strip().lower()
        if network_mode not in NETWORK_MODES:
            raise ValueError(
                "LIVEOPT_MCP_NETWORK_MODE must be one of: "
                + ", ".join(sorted(NETWORK_MODES))
            )
        return cls(
            state_dir=state_dir,
            workspace_root=workspace_root,
            cache_mode=cache_mode,
            network_mode=network_mode,
            max_workers=max(1, int(os.getenv("LIVEOPT_MCP_MAX_WORKERS", "2"))),
            max_result_archive=max(
                1, int(os.getenv("LIVEOPT_MCP_MAX_RESULT_ARCHIVE", "50"))
            ),
            default_model=os.getenv(
                "LIVEOPT_MCP_DEFAULT_MODEL", "deepseek-v4-flash"
            ).strip(),
            solver_time_limit_seconds=max(
                1.0,
                float(os.getenv("LIVEOPT_MCP_SOLVER_TIME_LIMIT_SECONDS", "30")),
            ),
        )

    def prepare_environment(self) -> None:
        """Set one cache policy for the sidecar process before workers start."""

        self.state_dir.mkdir(parents=True, exist_ok=True)
        workspace_root = self.workspace_root.expanduser().resolve()
        if not workspace_root.is_dir():
            raise ValueError(
                f"LIVEOPT_MCP_WORKSPACE_ROOT must be an existing directory: {workspace_root}"
            )
        enabled = self.cache_mode != "off"
        cache_only = self.cache_mode == "cache_only"
        os.environ["DEEPSEEK_CACHE"] = "1" if enabled else "0"
        os.environ["KIMI_CACHE"] = "1" if enabled else "0"
        os.environ["LIVEOPT_SEMANTIC_RESTART_CACHE"] = "1" if enabled else "0"
        _set_or_clear("DEEPSEEK_CACHE_ONLY", cache_only)
        _set_or_clear("KIMI_CACHE_ONLY", cache_only)
        use_system_proxy = self.network_mode == "system_proxy" or (
            self.network_mode == "auto"
            and any(
                os.getenv(name)
                for name in ("HTTPS_PROXY", "https_proxy", "ALL_PROXY", "all_proxy")
            )
        )
        _set_or_clear("DEEPSEEK_USE_SYSTEM_PROXY", use_system_proxy)
        _set_or_clear("KIMI_USE_SYSTEM_PROXY", use_system_proxy)

        cache_root = self.state_dir / "cache"
        trace_root = self.state_dir / "provider_traces"
        # Never inherit the paper runner's cache or trace locations. Explicit
        # sidecar overrides use a separate LIVEOPT_MCP_* namespace.
        os.environ["DEEPSEEK_CACHE_DIR"] = os.getenv(
            "LIVEOPT_MCP_DEEPSEEK_CACHE_DIR", str(cache_root / "deepseek")
        )
        os.environ["KIMI_CACHE_DIR"] = os.getenv(
            "LIVEOPT_MCP_KIMI_CACHE_DIR", str(cache_root / "kimi")
        )
        os.environ["LIVEOPT_SEMANTIC_RESTART_CACHE_DIR"] = os.getenv(
            "LIVEOPT_MCP_RESTART_CACHE_DIR", str(cache_root / "semantic_restart")
        )
        os.environ["DEEPSEEK_TRACE_DIR"] = os.getenv(
            "LIVEOPT_MCP_DEEPSEEK_TRACE_DIR", str(trace_root / "deepseek")
        )
        os.environ["KIMI_TRACE_DIR"] = os.getenv(
            "LIVEOPT_MCP_KIMI_TRACE_DIR", str(trace_root / "kimi")
        )
        os.environ["LIVEOPT_MCP_SOLVER_TIME_LIMIT_SECONDS"] = str(
            self.solver_time_limit_seconds
        )


def _set_or_clear(name: str, enabled: bool) -> None:
    if enabled:
        os.environ[name] = "1"
    else:
        os.environ.pop(name, None)
