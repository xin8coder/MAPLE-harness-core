from __future__ import annotations

import stat
from pathlib import Path

from demo.fake_client import fake_client_factory
from liveopt_dsh.app_settings import (
    credential_status,
    load_application_settings,
    load_deepseek_api_key,
    save_application_settings,
    save_deepseek_api_key,
)
from liveopt_dsh.config import ServiceConfig
from liveopt_dsh.service import LiveOptService


PROBLEM = (
    "Select records from the items table to maximize value while total weight "
    "does not exceed constraints.capacity."
)
CONTEXT = {
    "tables": {
        "items": [
            {"id": "I1", "value": 10, "weight": 4},
            {"id": "I2", "value": 8, "weight": 5},
        ],
        "constraints": [{"capacity": 8}],
    }
}


def test_application_settings_default_to_ten_and_store_owner_only(tmp_path: Path):
    state = tmp_path / "state"
    assert load_application_settings(state)["generations"] == 100
    saved = save_application_settings(state, generations=7)
    assert saved["generations"] == 7
    path = state / "application_settings.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert load_application_settings(state)["generations"] == 7


def test_deepseek_key_uses_harness_credential_document(tmp_path: Path, monkeypatch):
    credential_file = tmp_path / ".credentials.yaml"
    monkeypatch.setenv("LIVEOPT_DSH_CREDENTIAL_FILE", str(credential_file))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    save_deepseek_api_key("sk-liveopt-example-1234")
    assert load_deepseek_api_key() == "sk-liveopt-example-1234"
    assert credential_status() == {
        "configured": True,
        "masked": "sk-l...1234",
        "credential_ref": "DEEPSEEK_API_KEY",
    }
    assert stat.S_IMODE(credential_file.stat().st_mode) == 0o600


def test_omitted_generations_use_application_setting(tmp_path: Path):
    save_application_settings(tmp_path / "state", generations=2)
    service = LiveOptService(
        ServiceConfig(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path,
            max_workers=1,
            max_result_archive=10,
        ),
        client_factory=fake_client_factory,
    )
    try:
        started = service.submit_start(
            problem=PROBLEM,
            public_context=CONTEXT,
            provider="deepseek",
            model="fake-demo",
            population_size=8,
        )
        job = service.wait_for_job(started["job_id"], timeout_seconds=10)
        assert job["status"] == "succeeded", job.get("error")
        assert job["progress"]["total_generations"] == 2
        snapshot = service.store.load_snapshot(started["session_id"])
        assert snapshot["search"]["generations"] == 2
        event = service.store.load_event(started["session_id"], 0)
        assert event["setup_code"]
        assert event["fitness_code"]
        assert event["segments"]
    finally:
        service.close()
