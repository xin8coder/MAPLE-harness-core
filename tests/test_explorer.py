from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from liveopt_dsh.explorer import save_preference, solution_options
from liveopt_dsh.store import StateStore
from liveopt_dsh.web_api import make_handler


def candidate(x, y, *, feasible=True, name=None):
    return {"genome": {"x": x, "y": y}, "objectives": [x, y], "feasible": feasible,
            "solution": {"name": name or f"{x}-{y}"}, "violations": {} if feasible else {"capacity": 1}}


@pytest.fixture
def store(tmp_path):
    store = StateStore(tmp_path)
    store.save_snapshot("test-session", {"turn": 1, "task_id": "Test", "result": {"population": []}})
    store.save_event("test-session", 0, "initial", {"problem": "Initial request", "accepted": {}})
    store.save_event("test-session", 1, "update", {"natural_language_update": "Updated request", "accepted": {}})
    rows = [candidate(1, 5), candidate(2, 2), candidate(5, 1), candidate(3, 3), candidate(0, 0, feasible=False)]
    for turn in (0, 1):
        store.save_session_bytes("test-session", f"exports/t{turn:03d}/result_bundle.json", json.dumps({
            "session": {"objective_names": ["cost", "delay"]},
            "final_population": rows, "solution_set": rows[:3], "best": rows[0],
        }).encode())
    return store


def test_full_candidates_pareto_and_deduplication(store):
    result = solution_options(store, "test-session", 0)
    assert result["counts"] == {"total": 5, "feasible": 4, "pareto": 3}
    assert result["requirement"] == "Initial request"
    assert result["candidates"][0]["sources"] == ["population", "archive", "best"]
    assert not result["candidates"][3]["pareto"]
    assert not result["candidates"][4]["selectable"]


def test_preferences_are_independent_and_bound_to_turn(store):
    before = store.snapshot_path("test-session").read_bytes()
    first = solution_options(store, "test-session", 0)["candidates"][1]
    preference = save_preference(store, "test-session", 0, first["id"])
    assert preference["label"] == "S002"
    assert solution_options(store, "test-session", 0)["preference"] == preference
    assert solution_options(store, "test-session", 1)["preference"] is None
    assert store.snapshot_path("test-session").read_bytes() == before
    with pytest.raises(KeyError):
        save_preference(store, "test-session", 0, "not-in-this-turn")
    with pytest.raises(ValueError):
        save_preference(store, "test-session", 0, solution_options(store, "test-session", 0)["candidates"][-1]["id"])


@pytest.mark.parametrize("turn", [None, True, -1, 2, "0", 0.5])
def test_invalid_preference_turn_rejected(store, turn):
    with pytest.raises(ValueError):
        save_preference(store, "test-session", turn, "x")


def test_missing_historical_population_never_uses_latest(store):
    store.resolve_artifact("sessions/test-session/exports/t000/result_bundle.json").unlink()
    result = solution_options(store, "test-session", 0)
    assert result["coverage"] == "retained_archive_only"
    assert result["candidates"] == []


def test_demo_business_validation_failure_blocks_selection(store):
    snapshot = store.load_snapshot("test-session")
    snapshot["demo_metadata"] = {"validation": "failed"}
    store.save_snapshot("test-session", snapshot)
    candidate_id = solution_options(store, "test-session", 0)["candidates"][0]["id"]
    with pytest.raises(ValueError, match="business-rule validation"):
        save_preference(store, "test-session", 0, candidate_id)


def test_latest_snapshot_fallback_and_nonfinite(store):
    store.resolve_artifact("sessions/test-session/exports/t001/result_bundle.json").unlink()
    rows = [candidate(1, 5), candidate(float("nan"), 1)]
    store.save_snapshot("test-session", {"turn": 1, "result": {
        "population": [{"genome": row.pop("genome"), "result": row} for row in rows],
    }})
    payload = solution_options(store, "test-session")
    assert payload["counts"] == {"total": 2, "feasible": 1, "pareto": 1}
    assert not payload["candidates"][1]["plottable"]


def test_http_assets_and_selection(store):
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{server.server_port}"
    try:
        for file in ("index.html", "explorer.js", "solution-view.js", "explorer.css", "echarts.min.js", "lucide.min.js"):
            with urllib.request.urlopen(f"{base}/explorer/{file}") as response:
                assert response.status == 200
                assert "script-src 'self'" in response.headers["Content-Security-Policy"]
        with urllib.request.urlopen(base + "/solution-options/test-session?turn=0") as response:
            payload = json.load(response)
        request = urllib.request.Request(base + "/solution-preferences/test-session", method="POST",
            headers={"Content-Type": "application/json"},
            data=json.dumps({"turn": 0, "candidate_id": payload["candidates"][0]["id"]}).encode())
        with urllib.request.urlopen(request) as response:
            assert json.load(response)["kind"] == "user_preference"
        with pytest.raises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(base + "/explorer/../web_api.py")
        assert error.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
