"""LiveOpt application preferences and DeepSeek credential storage.

This module belongs to the isolated Harness integration.  It deliberately
does not read or write any paper experiment configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


DEFAULT_GENERATIONS = 100
MIN_GENERATIONS = 1
MAX_GENERATIONS = 1000
DEEPSEEK_CREDENTIAL_REF = "DEEPSEEK_API_KEY"


def load_application_settings(state_dir: Path) -> dict[str, Any]:
    """Return validated non-secret application settings."""

    path = application_settings_path(state_dir)
    payload: dict[str, Any] = {}
    if path.is_file():
        try:
            candidate = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(candidate, dict):
                payload = candidate
        except (OSError, ValueError):
            payload = {}
    return {
        "schema_version": 1,
        "generations": validate_generations(
            payload.get("generations", DEFAULT_GENERATIONS)
        ),
    }


def save_application_settings(
    state_dir: Path,
    *,
    generations: int,
) -> dict[str, Any]:
    """Persist non-secret application settings atomically."""

    payload = {
        "schema_version": 1,
        "generations": validate_generations(generations),
    }
    _atomic_text(
        application_settings_path(state_dir),
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        mode=0o600,
    )
    return payload


def validate_generations(value: Any) -> int:
    try:
        generations = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("generations must be an integer") from exc
    if not MIN_GENERATIONS <= generations <= MAX_GENERATIONS:
        raise ValueError(
            f"generations must be between {MIN_GENERATIONS} and {MAX_GENERATIONS}"
        )
    return generations


def application_settings_path(state_dir: Path) -> Path:
    return Path(state_dir).expanduser().resolve() / "application_settings.json"


def credentials_path() -> Path:
    explicit = os.getenv("LIVEOPT_DSH_CREDENTIAL_FILE", "").strip()
    if explicit:
        return Path(explicit).expanduser().resolve()
    dsh_home = Path(os.getenv("DSH_HOME", "~/.dsh")).expanduser().resolve()
    return dsh_home / ".credentials.yaml"


def credential_status() -> dict[str, Any]:
    key = load_deepseek_api_key()
    return {
        "configured": bool(key),
        "masked": _masked_key(key),
        "credential_ref": DEEPSEEK_CREDENTIAL_REF,
    }


def load_deepseek_api_key() -> str:
    """Resolve the application key from Harness storage, then the environment."""

    stored = _load_credentials().get(DEEPSEEK_CREDENTIAL_REF)
    if isinstance(stored, str) and stored.strip():
        return stored.strip()
    return os.getenv(DEEPSEEK_CREDENTIAL_REF, "").strip()


def save_deepseek_api_key(value: str) -> None:
    """Store the key in the same owner-only document watched by Harness."""

    key = str(value or "").strip()
    if not key:
        raise ValueError("API key cannot be empty")
    payload = _load_credentials()
    payload[DEEPSEEK_CREDENTIAL_REF] = key
    _atomic_text(
        credentials_path(),
        yaml.safe_dump(payload, allow_unicode=True, sort_keys=True),
        mode=0o600,
    )


def _load_credentials() -> dict[str, str]:
    path = credentials_path()
    if not path.is_file():
        return {}
    try:
        candidate = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    if not isinstance(candidate, dict):
        return {}
    return {
        str(key): value
        for key, value in candidate.items()
        if isinstance(key, str) and isinstance(value, str) and value
    }


def _masked_key(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


def _atomic_text(path: Path, payload: str, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        os.chmod(path, mode)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def main() -> None:
    parser = argparse.ArgumentParser(description="Configure the LiveOpt Harness application")
    parser.add_argument("--api-key")
    parser.add_argument("--generations", type=int)
    parser.add_argument(
        "--state-dir",
        default=os.getenv("LIVEOPT_MCP_STATE_DIR", "~/.local/share/liveopt-dsh/state"),
    )
    args = parser.parse_args()
    state_dir = Path(args.state_dir).expanduser()
    if args.api_key:
        save_deepseek_api_key(args.api_key)
    current = load_application_settings(state_dir)
    if args.generations is not None:
        current = save_application_settings(state_dir, generations=args.generations)
    print(
        json.dumps(
            {**current, "api": credential_status()},
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
