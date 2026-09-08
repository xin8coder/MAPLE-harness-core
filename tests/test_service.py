from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from demo.fake_client import fake_client_factory
from evo2.agents.deepseek_client import DeepSeekDebugClient
from evo2.agents.liveopt_state_binding import apply_state_bindings
from liveopt_dsh.config import ServiceConfig
from liveopt_dsh.service import LiveOptService
from liveopt_dsh.store import StateStore


PROBLEM = (
    "Select items from the items table to maximize total value. The sum of item "
    "weights must not exceed constraints.capacity. Return selected public item ids."
)
CONTEXT = {
    "tables": {
        "items": [
            {"id": "I1", "value": 10, "weight": 4},
            {"id": "I2", "value": 8, "weight": 5},
            {"id": "I3", "value": 6, "weight": 3},
        ],
        "constraints": [{"capacity": 8}],
    }
}


def _service(tmp_path: Path, *, cache_mode: str = "read_write") -> LiveOptService:
    return LiveOptService(
        ServiceConfig(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path,
            cache_mode=cache_mode,
            max_workers=2,
            max_result_archive=20,
        ),
        client_factory=fake_client_factory,
    )


def _wait(service: LiveOptService, job_id: str, timeout: float = 10.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = service.inspect(job_id=job_id)
        if job["status"] in {"succeeded", "failed", "cancelled", "interrupted"}:
            return job
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not finish")


def test_start_update_and_trace_are_persisted(tmp_path: Path):
    service = _service(tmp_path)
    try:
        started = service.submit_start(
            problem=PROBLEM,
            public_context=CONTEXT,
            provider="deepseek",
            model="fake-demo",
            population_size=12,
            generations=6,
            archive_limit=20,
        )
        start_job = _wait(service, started["job_id"])
        assert start_job["status"] == "succeeded", start_job.get("error")
        assert start_job["phase"] == "completed"
        assert start_job["elapsed_seconds"] >= 0.0
        assert start_job["progress"]["generation"] == 6
        assert start_job["progress"]["total_generations"] == 6
        assert start_job["progress"]["feasible_count"] > 0
        session_id = started["session_id"]
        summary = service.inspect(session_id=session_id)
        assert summary["turn"] == 0
        assert summary["accepted"]["best"]["feasible"] is True

        queued = service.submit_update(
            session_id=session_id,
            update_id="t001",
            update="Item I1 now has public value 15.",
        )
        update_job = _wait(service, queued["job_id"])
        assert update_job["status"] == "succeeded", update_job.get("error")
        assert update_job["result"]["restart_skill"] == "warm_restart_v1"
        assert update_job["progress"]["restart_skill"] == "warm_restart_v1"
        assert update_job["progress"]["reused_solution_count"] > 0
        assert update_job["progress"]["restart_source"]

        snapshot = json.loads(
            (tmp_path / "state" / "sessions" / session_id / "snapshot.json").read_text()
        )
        assert snapshot["turn"] == 1
        assert len(snapshot["result"]["population"]) == 12
        assert snapshot["public_update_history"][0]["update_id"] == "t001"
        assert "api_key" not in json.dumps(snapshot).lower()
        trace = service.inspect(session_id=session_id, view="trace", turn=1)
        assert trace["patch_trace"]["prompts"]
        assert trace["patch_trace"]["raw_responses"]
    finally:
        service.close()


def test_session_rehydrates_after_sidecar_restart(tmp_path: Path):
    first = _service(tmp_path)
    started = first.submit_start(
        problem=PROBLEM,
        public_context=CONTEXT,
        provider="deepseek",
        model="fake-demo",
        population_size=10,
        generations=4,
    )
    assert _wait(first, started["job_id"])["status"] == "succeeded"
    session_id = started["session_id"]
    first.close()

    second = _service(tmp_path)
    try:
        before = second.inspect(session_id=session_id)
        assert before["turn"] == 0
        queued = second.submit_update(
            session_id=session_id,
            update_id="t001",
            update="Item I1 now has public value 15.",
        )
        job = _wait(second, queued["job_id"])
        assert job["status"] == "succeeded", job.get("error")
        after = second.inspect(session_id=session_id)
        assert after["turn"] == 1
        assert after["update_count"] == 1
    finally:
        second.close()


def test_rehydration_reapplies_persisted_state_bindings(tmp_path: Path):
    first = _service(tmp_path)
    started = first.submit_start(
        problem=PROBLEM,
        public_context=CONTEXT,
        provider="deepseek",
        model="fake-demo",
        population_size=10,
        generations=4,
    )
    assert _wait(first, started["job_id"])["status"] == "succeeded"
    session_id = started["session_id"]
    runtime = first._runtime(session_id)
    binding = {
        "binding_id": "persisted-binding",
        "kind": "lock_assignment",
        "segment": "select",
        "assignments": {"I1": 1},
    }
    runtime.runner.project = apply_state_bindings(runtime.runner.project, [binding])
    first.store.save_snapshot(session_id, first._snapshot(runtime))
    first.close()

    second = _service(tmp_path)
    try:
        restored = second._runtime(session_id)
        assert restored.runner.project.problem_spec["state_bindings"] == [binding]
        assert restored.runner.project.data["state_bindings"] == [binding]
    finally:
        second.close()


def test_repeated_update_id_is_idempotent(tmp_path: Path):
    service = _service(tmp_path)
    try:
        started = service.submit_start(
            problem=PROBLEM,
            public_context=CONTEXT,
            provider="deepseek",
            model="fake-demo",
            population_size=10,
            generations=4,
        )
        assert _wait(service, started["job_id"])["status"] == "succeeded"
        args = {
            "session_id": started["session_id"],
            "update_id": "t001",
            "update": "Item I1 now has public value 15.",
        }
        first = service.submit_update(**args)
        assert _wait(service, first["job_id"])["status"] == "succeeded"
        repeated = service.submit_update(**args)
        job = _wait(service, repeated["job_id"])
        assert job["status"] == "succeeded"
        assert job["result"]["idempotent"] is True
        assert service.inspect(session_id=started["session_id"])["turn"] == 1
    finally:
        service.close()


def test_manual_slot_override_continues_the_same_session(tmp_path: Path):
    service = _service(tmp_path)
    try:
        started = service.submit_start(
            problem=PROBLEM,
            public_context=CONTEXT,
            provider="deepseek",
            model="fake-demo",
            population_size=10,
            generations=4,
        )
        assert _wait(service, started["job_id"])["status"] == "succeeded"
        session_id = started["session_id"]
        workbench = service.inspect(session_id=session_id, view="workbench")
        override = service.submit_slot_override(
            session_id=session_id,
            fitness_code="```python\n" + workbench["slots"]["fitness.py"] + "\n```",
        )
        job = _wait(service, override["job_id"])
        assert job["status"] == "succeeded", job.get("error")
        assert job["result"]["session_id"] == session_id
        assert job["result"]["turn"] == 1
        trace = service.inspect(session_id=session_id, view="trace", turn=1)
        assert trace["kind"] == "manual_slot_override"
        assert trace["slot_names"] == ["fitness.py"]
    finally:
        service.close()


def test_cache_policy_and_workspace_boundary(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("DEEPSEEK_CACHE_ONLY", raising=False)
    monkeypatch.delenv("KIMI_CACHE_ONLY", raising=False)
    service = _service(tmp_path, cache_mode="cache_only")
    try:
        assert service.config.cache_mode == "cache_only"
        assert service.store.root == (tmp_path / "state").resolve()
        assert service.config.workspace_root == tmp_path
        assert __import__("os").environ["DEEPSEEK_CACHE_ONLY"] == "1"
        outside = tmp_path.parent / "outside-liveopt-context.json"
        outside.write_text(json.dumps(CONTEXT), encoding="utf-8")
        with pytest.raises(ValueError, match="inside LIVEOPT_MCP_WORKSPACE_ROOT"):
            service.submit_start(problem=PROBLEM, public_context_path=str(outside))
    finally:
        service.close()


def test_cache_only_uses_existing_provider_response_without_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "LIVEOPT_MCP_DEEPSEEK_CACHE_DIR", str(tmp_path / "provider-cache")
    )
    monkeypatch.setenv(
        "LIVEOPT_MCP_DEEPSEEK_TRACE_DIR", str(tmp_path / "provider-traces")
    )
    config = ServiceConfig(
        state_dir=tmp_path / "state",
        workspace_root=tmp_path,
        cache_mode="cache_only",
    )
    config.prepare_environment()
    client = DeepSeekDebugClient(api_key="offline-key", model="deepseek-v4-pro")
    messages = [{"role": "user", "content": "cached request"}]
    payload = {"model": "deepseek-v4-pro", "messages": messages, "temperature": 0.0}
    cache_path = client._cache_path(payload)
    assert cache_path is not None
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "choices": [{"message": {"content": "cached response"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
            }
        ),
        encoding="utf-8",
    )

    def no_network(*_args, **_kwargs):
        raise AssertionError("cache hit unexpectedly reached the network")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    response = client.chat(messages, max_tokens=32)
    assert response["choices"][0]["message"]["content"] == "cached response"
    assert response["usage"]["total_tokens"] == 0
    assert response["usage"]["local_cache_hits"] == 1


def test_sidecar_does_not_inherit_paper_cache_or_trace_dirs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    paper_cache = tmp_path / "paper-cache"
    paper_trace = tmp_path / "paper-trace"
    monkeypatch.setenv("DEEPSEEK_CACHE_DIR", str(paper_cache))
    monkeypatch.setenv("DEEPSEEK_TRACE_DIR", str(paper_trace))
    monkeypatch.delenv("LIVEOPT_MCP_DEEPSEEK_CACHE_DIR", raising=False)
    monkeypatch.delenv("LIVEOPT_MCP_DEEPSEEK_TRACE_DIR", raising=False)
    config = ServiceConfig(
        state_dir=tmp_path / "plugin-state",
        workspace_root=tmp_path,
    )
    config.prepare_environment()
    import os

    assert os.environ["DEEPSEEK_CACHE_DIR"] == str(
        tmp_path / "plugin-state/cache/deepseek"
    )
    assert os.environ["DEEPSEEK_TRACE_DIR"] == str(
        tmp_path / "plugin-state/provider_traces/deepseek"
    )


def test_auto_network_mode_uses_available_system_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    config = ServiceConfig(
        state_dir=tmp_path / "plugin-state",
        workspace_root=tmp_path,
        network_mode="auto",
    )
    config.prepare_environment()
    import os

    assert os.environ["DEEPSEEK_USE_SYSTEM_PROXY"] == "1"
    assert os.environ["KIMI_USE_SYSTEM_PROXY"] == "1"


def test_direct_network_mode_ignores_available_system_proxy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("HTTPS_PROXY", "http://127.0.0.1:7890")
    config = ServiceConfig(
        state_dir=tmp_path / "plugin-state",
        workspace_root=tmp_path,
        network_mode="direct",
    )
    config.prepare_environment()
    import os

    assert "DEEPSEEK_USE_SYSTEM_PROXY" not in os.environ
    assert "KIMI_USE_SYSTEM_PROXY" not in os.environ


def test_solver_preference_is_validated_and_persisted(tmp_path: Path):
    service = _service(tmp_path)
    try:
        with pytest.raises(ValueError, match="solver_preference"):
            service.submit_start(
                problem=PROBLEM,
                public_context=CONTEXT,
                solver_preference="guess",
            )
        started = service.submit_start(
            problem=PROBLEM,
            public_context=CONTEXT,
            provider="deepseek",
            model="fake-demo",
            solver_preference="evolutionary",
            population_size=8,
            generations=3,
        )
        job = _wait(service, started["job_id"])
        assert job["status"] == "succeeded", job.get("error")
        summary = service.inspect(session_id=started["session_id"])
        assert summary["solver_preference"] == "evolutionary"
    finally:
        service.close()


def test_production_service_rejects_non_flash_model(tmp_path: Path):
    service = LiveOptService(
        ServiceConfig(state_dir=tmp_path / "state", workspace_root=tmp_path)
    )
    try:
        with pytest.raises(ValueError, match="deepseek-v4-flash"):
            service.submit_start(
                problem=PROBLEM,
                public_context=CONTEXT,
                provider="deepseek",
                model="deepseek-v4-pro",
            )
    finally:
        service.close()


def test_running_job_is_marked_interrupted_after_process_recovery(tmp_path: Path):
    store = StateStore(tmp_path / "state")
    store.save_job(
        "job-before-crash",
        {
            "job_id": "job-before-crash",
            "kind": "update",
            "session_id": "session-a",
            "request": {"update_id": "t001"},
            "status": "running",
            "created_at": 1.0,
            "started_at": 2.0,
            "finished_at": None,
            "result": None,
            "error": None,
        },
    )
    assert store.recover_interrupted_jobs() == 1
    recovered = store.load_job("job-before-crash")
    assert recovered["status"] == "interrupted"
    assert recovered["finished_at"] is not None
    assert "Resubmit the same session/update id" in recovered["error"]["message"]
