"""Small persistent job manager so MCP calls never wait for an optimization run."""

from __future__ import annotations

import threading
import time
import traceback
import uuid
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

from .serialization import json_safe
from .store import StateStore


TERMINAL_STATUSES = frozenset({"succeeded", "failed", "cancelled", "interrupted"})


@dataclass
class JobRecord:
    job_id: str
    kind: str
    session_id: str
    request: dict[str, Any]
    status: str = "queued"
    phase: str = "queued"
    progress: dict[str, Any] = field(default_factory=dict)
    result: dict[str, Any] | None = None
    error: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    updated_at: float | None = None
    finished_at: float | None = None

    def to_record(self) -> dict[str, Any]:
        return json_safe(self.__dict__)


class JobManager:
    def __init__(self, store: StateStore, max_workers: int):
        self.store = store
        self.executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="liveopt")
        self._records: dict[str, JobRecord] = {}
        self._futures: dict[str, Future[Any]] = {}
        self._active_sessions: set[str] = set()
        self._lock = threading.RLock()
        self.store.recover_interrupted_jobs()

    def submit(
        self,
        *,
        kind: str,
        session_id: str,
        request: dict[str, Any],
        operation: Callable[[Callable[..., None]], dict[str, Any]],
    ) -> JobRecord:
        with self._lock:
            if session_id in self._active_sessions:
                raise RuntimeError(f"session {session_id} already has an active job")
            job = JobRecord(
                job_id=uuid.uuid4().hex[:16],
                kind=kind,
                session_id=session_id,
                request=json_safe(request),
            )
            self._records[job.job_id] = job
            self._active_sessions.add(session_id)
            self.store.save_job(job.job_id, job.to_record())
            future = self.executor.submit(self._run, job.job_id, operation)
            self._futures[job.job_id] = future
            return job

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._records.get(job_id)
            if record is not None:
                payload = record.to_record()
            else:
                payload = self.store.load_job(job_id)
        started = payload.get("started_at") or payload.get("created_at") or time.time()
        stopped = payload.get("finished_at") or time.time()
        payload["elapsed_seconds"] = round(max(0.0, float(stopped) - float(started)), 3)
        return payload

    def cancel(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            record = self._records.get(job_id)
            future = self._futures.get(job_id)
            if record is None or future is None:
                stored = self.store.load_job(job_id)
                return {
                    "job_id": job_id,
                    "status": stored.get("status"),
                    "cancelled": False,
                    "reason": "job is not active in this sidecar process",
                }
            if record.status != "queued":
                return {
                    "job_id": job_id,
                    "status": record.status,
                    "cancelled": False,
                    "reason": "running LiveOpt calls commit atomically and cannot be interrupted safely",
                }
            cancelled = future.cancel()
            if cancelled:
                record.status = "cancelled"
                record.phase = "cancelled"
                record.finished_at = time.time()
                record.updated_at = record.finished_at
                self._active_sessions.discard(record.session_id)
                self.store.save_job(job_id, record.to_record())
            return {"job_id": job_id, "status": record.status, "cancelled": cancelled}

    def close(self, wait: bool = True) -> None:
        self.executor.shutdown(wait=wait, cancel_futures=False)

    def _run(
        self,
        job_id: str,
        operation: Callable[[Callable[..., None]], dict[str, Any]],
    ) -> None:
        with self._lock:
            record = self._records[job_id]
            if record.status == "cancelled":
                return
            record.status = "running"
            record.phase = "starting"
            record.started_at = time.time()
            record.updated_at = record.started_at
            self.store.save_job(job_id, record.to_record())

        def report(phase: str, **details: Any) -> None:
            with self._lock:
                record.phase = str(phase)
                record.progress = {
                    **record.progress,
                    **json_safe(details),
                }
                record.updated_at = time.time()
                self.store.save_job(job_id, record.to_record())

        try:
            result = operation(report)
        except BaseException as exc:  # noqa: BLE001 - job boundary records every failure
            with self._lock:
                record.status = "failed"
                record.phase = "failed"
                record.error = {
                    "type": type(exc).__name__,
                    "message": str(exc)[:4000],
                    "traceback": traceback.format_exc(limit=20)[-12000:],
                }
        else:
            with self._lock:
                record.status = "succeeded"
                record.phase = "completed"
                record.result = json_safe(result)
        finally:
            with self._lock:
                record.finished_at = time.time()
                record.updated_at = record.finished_at
                self._active_sessions.discard(record.session_id)
                self.store.save_job(job_id, record.to_record())
