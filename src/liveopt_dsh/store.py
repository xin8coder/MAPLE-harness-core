"""Atomic session, job, and trace storage owned only by the MCP integration."""

from __future__ import annotations

import json
import hashlib
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

from .serialization import json_safe


_SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")


class StateStore:
    def __init__(self, root: Path):
        self.root = root.resolve()
        self.sessions_dir = self.root / "sessions"
        self.jobs_dir = self.root / "jobs"
        self.uploads_dir = self.root / "uploads"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir.mkdir(parents=True, exist_ok=True)
        self.uploads_dir.mkdir(parents=True, exist_ok=True)

    def session_exists(self, session_id: str) -> bool:
        return self.snapshot_path(session_id).exists()

    def snapshot_path(self, session_id: str) -> Path:
        return self._session_dir(session_id) / "snapshot.json"

    def save_snapshot(self, session_id: str, record: dict[str, Any]) -> Path:
        path = self.snapshot_path(session_id)
        _atomic_json(path, record)
        return path

    def load_snapshot(self, session_id: str) -> dict[str, Any]:
        path = self.snapshot_path(session_id)
        if not path.exists():
            raise KeyError(f"unknown LiveOpt session: {session_id}")
        return _read_json(path)

    def save_event(self, session_id: str, turn: int, kind: str, record: dict[str, Any]) -> Path:
        safe_kind = _checked_id(kind)
        path = self._session_dir(session_id) / "events" / f"{turn:04d}-{safe_kind}.json"
        _atomic_json(path, record)
        return path

    def load_event(self, session_id: str, turn: int) -> dict[str, Any]:
        event_dir = self._session_dir(session_id) / "events"
        matches = sorted(event_dir.glob(f"{int(turn):04d}-*.json"))
        if not matches:
            raise KeyError(f"session {session_id} has no event for turn {turn}")
        return _read_json(matches[0])

    def save_prepared_data(self, data_id: str, record: dict[str, Any]) -> Path:
        path = self.root / "prepared_data" / f"{_checked_id(data_id)}.json"
        _atomic_json(path, record)
        return path

    def load_prepared_data(self, data_id: str) -> dict[str, Any]:
        path = self.root / "prepared_data" / f"{_checked_id(data_id)}.json"
        if not path.exists():
            raise KeyError(f"unknown prepared data: {data_id}")
        return _read_json(path)

    def save_upload(
        self,
        *,
        filename: str,
        media_type: str,
        payload: bytes,
    ) -> dict[str, Any]:
        """Persist one immutable browser upload and return its public metadata."""

        safe_filename = _safe_filename(filename)
        digest = hashlib.sha256(payload).hexdigest()
        identity = hashlib.sha256(
            safe_filename.encode("utf-8") + b"\0" + payload
        ).hexdigest()[:24]
        upload_dir = self.uploads_dir / identity
        suffix = Path(safe_filename).suffix.lower()
        content_name = f"content{suffix}"
        content_path = self._safe_descendant(upload_dir, content_name)
        metadata = {
            "schema_version": 1,
            "upload_id": identity,
            "filename": safe_filename,
            "media_type": str(media_type or "application/octet-stream"),
            "size_bytes": len(payload),
            "sha256": digest,
            "content_path": str(content_path.relative_to(self.root)),
            "created_at": time.time(),
        }
        upload_dir.mkdir(parents=True, exist_ok=True)
        if not content_path.exists():
            _atomic_bytes(content_path, payload)
        _atomic_json(upload_dir / "metadata.json", metadata)
        return metadata

    def load_upload(self, upload_id: str) -> dict[str, Any]:
        path = self.uploads_dir / _checked_id(upload_id) / "metadata.json"
        if not path.exists():
            raise KeyError(f"unknown LiveOpt upload: {upload_id}")
        return _read_json(path)

    def resolve_upload(self, upload_id: str) -> tuple[dict[str, Any], Path]:
        metadata = self.load_upload(upload_id)
        path = self.resolve_artifact(str(metadata["content_path"]))
        if path.stat().st_size != int(metadata["size_bytes"]):
            raise ValueError(f"uploaded document size mismatch: {upload_id}")
        if hashlib.sha256(path.read_bytes()).hexdigest() != metadata["sha256"]:
            raise ValueError(f"uploaded document checksum mismatch: {upload_id}")
        return metadata, path

    def save_session_bytes(self, session_id: str, relative_path: str, payload: bytes) -> Path:
        path = self._safe_descendant(self._session_dir(session_id), relative_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
        )
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, path)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
        return path

    def resolve_artifact(self, relative_path: str) -> Path:
        path = self._safe_descendant(self.root, relative_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def list_artifacts(self, session_id: str) -> list[str]:
        session_dir = self._session_dir(session_id)
        if not session_dir.exists():
            raise KeyError(f"unknown LiveOpt session: {session_id}")
        return [str(path.relative_to(self.root)) for path in sorted(session_dir.rglob("*")) if path.is_file()]

    def save_job(self, job_id: str, record: dict[str, Any]) -> Path:
        path = self.jobs_dir / f"{_checked_id(job_id)}.json"
        _atomic_json(path, record)
        return path

    def load_job(self, job_id: str) -> dict[str, Any]:
        path = self.jobs_dir / f"{_checked_id(job_id)}.json"
        if not path.exists():
            raise KeyError(f"unknown LiveOpt job: {job_id}")
        return _read_json(path)

    def recover_interrupted_jobs(self) -> int:
        count = 0
        for path in self.jobs_dir.glob("*.json"):
            record = _read_json(path)
            if record.get("status") not in {"queued", "running"}:
                continue
            record["status"] = "interrupted"
            record["finished_at"] = time.time()
            record["error"] = {
                "type": "SidecarRestarted",
                "message": "The sidecar stopped before this job committed. Resubmit the same session/update id; provider cache entries are reusable.",
            }
            _atomic_json(path, record)
            count += 1
        return count

    def resolve_public_path(self, raw_path: str, workspace_root: Path) -> Path:
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_root / candidate
        resolved = candidate.resolve(strict=True)
        root = workspace_root.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as exc:
            raise ValueError("public_context_path must stay inside LIVEOPT_MCP_WORKSPACE_ROOT") from exc
        if not resolved.is_file():
            raise ValueError(f"public_context_path is not a file: {resolved}")
        return resolved

    def _session_dir(self, session_id: str) -> Path:
        return self.sessions_dir / _checked_id(session_id)

    @staticmethod
    def _safe_descendant(root: Path, relative_path: str) -> Path:
        relative = Path(str(relative_path or ""))
        if relative.is_absolute():
            raise ValueError("artifact path must be relative")
        resolved_root = root.resolve()
        resolved = (resolved_root / relative).resolve()
        try:
            resolved.relative_to(resolved_root)
        except ValueError as exc:
            raise ValueError("artifact path escapes the LiveOpt state root") from exc
        return resolved


def _checked_id(value: str) -> str:
    value = str(value or "")
    if not _SAFE_ID.fullmatch(value):
        raise ValueError(f"unsafe identifier: {value!r}")
    return value


def _safe_filename(value: str) -> str:
    name = Path(str(value or "")).name.strip()
    if not name or name in {".", ".."}:
        raise ValueError("upload filename is required")
    cleaned = re.sub(r"[^A-Za-z0-9._()\- ]+", "_", name).strip(" .")
    if not cleaned:
        raise ValueError("upload filename contains no usable characters")
    return cleaned[:180]


def _atomic_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _atomic_json(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(json_safe(record), ensure_ascii=False, indent=2, sort_keys=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object in {path}")
    return payload
