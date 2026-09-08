from __future__ import annotations

import csv
import io
import json
import threading
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from demo.fake_client import fake_client_factory
from evo2.core.template_optimizer import Candidate, EvolutionResult, FitnessResult
from liveopt_dsh.config import ServiceConfig
from liveopt_dsh.exports import export_session
from liveopt_dsh.serialization import evolution_to_record
from liveopt_dsh.service import LiveOptService
from liveopt_dsh.store import StateStore
from liveopt_dsh.web_api import make_handler


PROBLEM = (
    "Select items from the items table to maximize total value. The sum of item "
    "weights must not exceed constraints.capacity. Return selected public item ids."
)


def _service(tmp_path: Path) -> LiveOptService:
    return LiveOptService(
        ServiceConfig(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path,
            max_workers=2,
            max_result_archive=20,
        ),
        client_factory=fake_client_factory,
    )


def test_public_data_skill_prepares_typed_tables_and_runs(tmp_path: Path):
    (tmp_path / "items.csv").write_text(
        "id,Value,Weight,Enabled,Display Code\n"
        "I001,10,4,yes,001\n"
        "I002,8,5,no,002\n"
        "I003,6,3,yes,003\n",
        encoding="utf-8",
    )
    (tmp_path / "constraints.json").write_text(
        json.dumps([{"capacity": 8}]), encoding="utf-8"
    )
    service = _service(tmp_path)
    try:
        prepared = service.prepare_data(
            [
                {
                    "path": "items.csv",
                    "table_name": "items",
                    "id_column": "id",
                },
                {"path": "constraints.json", "table_name": "constraints"},
            ]
        )
        assert prepared["prepared_data_id"]
        items = prepared["tables"][0]
        assert items["name"] == "items"
        assert items["rows"] == 3
        assert items["id_column"] == "id"
        record = service.store.load_prepared_data(prepared["prepared_data_id"])
        first = record["public_context"]["tables"]["items"][0]
        assert first == {
            "id": "I001",
            "value": 10,
            "weight": 4,
            "enabled": True,
            "display_code": "001",
        }

        started = service.submit_start(
            problem=PROBLEM,
            prepared_data_id=prepared["prepared_data_id"],
            provider="deepseek",
            model="fake-demo",
            population_size=10,
            generations=4,
        )
        job = service.wait_for_job(started["job_id"], timeout_seconds=10)
        assert job["status"] == "succeeded", job.get("error")
        assert job["result"]["accepted"]["best"]["feasible"] is True
    finally:
        service.close()


def test_result_skill_exports_solution_history_json_and_zip(tmp_path: Path):
    service = _service(tmp_path)
    try:
        started = service.submit_start(
            problem=PROBLEM,
            public_context={
                "tables": {
                    "items": [
                        {"id": "I1", "value": 10, "weight": 4},
                        {"id": "I2", "value": 8, "weight": 5},
                        {"id": "I3", "value": 6, "weight": 3},
                    ],
                    "constraints": [{"capacity": 8}],
                }
            },
            provider="deepseek",
            model="fake-demo",
            population_size=10,
            generations=4,
        )
        job = service.wait_for_job(started["job_id"], timeout_seconds=10)
        assert job["status"] == "succeeded", job.get("error")
        exported = service.export_results(started["session_id"])
        assert exported["solution_count"] >= 1
        assert exported["solution_preview"]
        assert len(exported["history_preview"]) == 5
        downloads = {item["name"]: item["url"] for item in exported["downloads"]}
        assert set(downloads) == {
            "solutions.csv",
            "final_population.csv",
            "iteration_history.csv",
            "result_bundle.json",
            "liveopt_results.zip",
        }
        root = (
            tmp_path
            / "state"
            / "sessions"
            / started["session_id"]
            / "exports"
            / "t000"
        )
        solutions = list(
            csv.DictReader(
                io.StringIO((root / "solutions.csv").read_text(encoding="utf-8-sig"))
            )
        )
        assert solutions
        assert "solution_json" in solutions[0]
        population = list(
            csv.DictReader(
                io.StringIO(
                    (root / "final_population.csv").read_text(encoding="utf-8-sig")
                )
            )
        )
        assert len(population) == 10
        assert "is_pareto" in population[0]
        history = list(
            csv.DictReader(
                io.StringIO(
                    (root / "iteration_history.csv").read_text(encoding="utf-8-sig")
                )
            )
        )
        assert [int(row["generation"]) for row in history] == [0, 1, 2, 3, 4]
        assert "objective_min_negative_value" in history[0]
        assert exported["population_count"] == 10
        assert exported["population_preview"]
        assert exported["pareto_preview"]
        assert exported["objective_series"][0]["name"] == "negative_value"
        ui_result = json.loads((root / "ui_result.json").read_text(encoding="utf-8"))
        assert ui_result["turn"] == 0
        assert ui_result["population_preview"] == exported["population_preview"]
        server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(service.store))
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/results/{started['session_id']}",
                timeout=2,
            ) as response:
                browser_result = json.loads(response.read())
            assert browser_result["turn"] == 0
            assert browser_result["pareto_preview"] == exported["pareto_preview"]
            with urllib.request.urlopen(
                f"http://127.0.0.1:{server.server_port}/results/{started['session_id']}?turn=0",
                timeout=2,
            ) as response:
                retained_turn = json.loads(response.read())
            assert retained_turn["turn"] == 0
            assert retained_turn["pareto_preview"] == exported["pareto_preview"]
            for brand_name in ("liveopt-mark-64.png", "maple-logo.png"):
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{server.server_port}/brand/{brand_name}",
                    timeout=2,
                ) as response:
                    brand_asset = response.read()
                    assert response.headers["Content-Type"] == "image/png"
                    assert response.headers["Cache-Control"] == "public, max-age=86400"
                assert brand_asset.startswith(b"\x89PNG\r\n\x1a\n")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
        with zipfile.ZipFile(root / "liveopt_results.zip") as archive:
            assert set(archive.namelist()) == {
                "solutions.csv",
                "final_population.csv",
                "iteration_history.csv",
                "result_bundle.json",
            }
    finally:
        service.close()


def test_data_skill_relationalizes_wide_entity_columns_and_inline_resources(
    tmp_path: Path,
):
    (tmp_path / "jobs.csv").write_text(
        "job_id,p_M1_h,p_M2_h,eligible_M1,eligible_M2\n"
        "J01,4.2,3.8,1,1\n"
        "J02,5.1,,1,0\n",
        encoding="utf-8",
    )
    service = _service(tmp_path)
    try:
        prepared = service.prepare_data(
            [{"path": "jobs.csv", "table_name": "jobs", "id_column": "job_id"}],
            inline_tables={
                "machines": [
                    {"id": "M1", "power_kw": 8.0},
                    {"id": "M2", "power_kw": 6.5},
                ]
            },
            column_groups=[
                {
                    "source_table": "jobs",
                    "output_table": "job_machine_options",
                    "source_id_column": "job_id",
                    "entity_id_name": "machine_id",
                    "entity_id_case": "upper",
                    "fields": {
                        "processing_h": "p_{id}_h",
                        "eligible": "eligible_{id}",
                    },
                }
            ],
        )
        record = service.store.load_prepared_data(prepared["prepared_data_id"])
        tables = record["public_context"]["tables"]
        assert tables["machines"][0] == {"id": "M1", "power_kw": 8.0}
        assert tables["job_machine_options"] == [
            {"job_id": "J01", "machine_id": "M1", "processing_h": 4.2, "eligible": 1},
            {"job_id": "J01", "machine_id": "M2", "processing_h": 3.8, "eligible": 1},
            {"job_id": "J02", "machine_id": "M1", "processing_h": 5.1, "eligible": 1},
            {"job_id": "J02", "machine_id": "M2", "processing_h": None, "eligible": 0},
        ]
    finally:
        service.close()


def test_multiobjective_export_preserves_population_front_and_each_objective_trace(
    tmp_path: Path,
):
    store = StateStore(tmp_path / "state")

    def candidate(index: int, objectives: list[float], *, rank: int) -> Candidate:
        return Candidate(
            genome={"x": [index]},
            result=FitnessResult(
                scalar=sum(objectives),
                objectives=objectives,
                feasible=True,
                solution={"id": index},
            ),
            rank=rank,
        )

    front = [candidate(0, [1.0, 4.0], rank=0), candidate(1, [2.0, 2.0], rank=0)]
    population = [*front, candidate(2, [4.0, 4.0], rank=1)]
    history = [
        {
            "generation": 0,
            "population": 3,
            "feasible": 3,
            "front_size": 1,
            "best_scalar": 6.0,
            "objective_min": [2.0, 4.0],
            "objective_mean": [3.0, 5.0],
            "objective_max": [4.0, 6.0],
        },
        {
            "generation": 1,
            "population": 3,
            "feasible": 3,
            "front_size": 2,
            "best_scalar": 4.0,
            "objective_min": [1.0, 2.0],
            "objective_mean": [2.0, 3.0],
            "objective_max": [4.0, 4.0],
        },
    ]
    result = EvolutionResult(
        best=front[1],
        population=population,
        archive=front,
        history=history,
        metadata={"selection": "nsga2"},
    )
    snapshot = {
        "session_id": "multi1",
        "task_id": "multi",
        "turn": 0,
        "solver_preference": "evolutionary",
        "problem_spec": {"objective_names": ["energy", "tardiness"]},
        "result": evolution_to_record(result),
    }
    store.save_snapshot("multi1", snapshot)
    store.save_event("multi1", 0, "initial", {"history": history})
    exported = export_session(store, "multi1")
    assert exported["population_count"] == 3
    assert len(exported["population_preview"]) == 3
    assert len(exported["pareto_preview"]) == 2
    assert [item["name"] for item in exported["objective_series"]] == [
        "energy",
        "tardiness",
    ]
    assert [point["minimum"] for point in exported["objective_series"][1]["points"]] == [
        4.0,
        2.0,
    ]


def test_browser_api_serves_live_jobs_and_only_state_artifacts(tmp_path: Path):
    store = StateStore(tmp_path / "state")
    store.save_job(
        "job123",
        {
            "job_id": "job123",
            "status": "running",
            "phase": "evolutionary_search",
            "created_at": 1.0,
            "started_at": 1.0,
            "progress": {"generation": 7, "total_generations": 20},
        },
    )
    store.save_session_bytes("session1", "exports/t000/solutions.csv", b"x\n1\n")
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(f"{base}/jobs/job123", timeout=2) as response:
            job = json.loads(response.read())
        assert job["progress"]["generation"] == 7
        with urllib.request.urlopen(
            f"{base}/artifacts/sessions/session1/exports/t000/solutions.csv",
            timeout=2,
        ) as response:
            assert response.read() == b"x\n1\n"
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(f"{base}/artifacts/../outside", timeout=2)
        assert caught.value.code == 404
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_api_serves_settings_and_solution_timeline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv(
        "LIVEOPT_DSH_CREDENTIAL_FILE", str(tmp_path / ".credentials.yaml")
    )
    store = StateStore(tmp_path / "state")
    best = {
        "feasible": True,
        "scalar": 3.0,
        "objectives": [1.0, 2.0],
        "solution": {"selected": ["A"]},
        "genome": {"pick": [1, 0]},
    }
    store.save_snapshot(
        "session-solutions",
        {
            "schema_version": 1,
            "session_id": "session-solutions",
            "task_id": "demo-task",
            "turn": 0,
            "created_at": 10.0,
            "updated_at": 11.0,
            "initial_problem": "Choose a feasible Pareto solution.",
            "solver_preference": "evolutionary",
            "problem_spec": {"objective_names": ["cost", "delay"]},
            "search": {"population_size": 8, "generations": 2},
            "slots": {"setup.py": "def build_problem():\n    return {}"},
            "result": {"best": best, "archive": [best], "population": [best]},
        },
    )
    store.save_event(
        "session-solutions",
        0,
        "initial",
        {
            "kind": "initial",
            "turn": 0,
            "problem": "Choose a feasible Pareto solution.",
            "accepted": {
                "best": best,
                "archive": [best],
                "archive_size": 1,
                "population_size": 1,
                "objective_names": ["cost", "delay"],
            },
            "history": [
                {
                    "generation": 1,
                    "population": 1,
                    "feasible": 1,
                    "front_size": 1,
                    "objective_min": [1.0, 2.0],
                    "objective_mean": [1.0, 2.0],
                    "objective_max": [1.0, 2.0],
                }
            ],
        },
    )
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(store))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"
        with urllib.request.urlopen(f"{base}/settings", timeout=2) as response:
            settings = json.loads(response.read())
        assert settings["generations"] == 100
        assert settings["theme"] == "light"

        request = urllib.request.Request(
            f"{base}/settings",
            data=json.dumps(
                {"generations": 6, "api_key": "sk-browser-test-1234"}
            ).encode(),
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=2) as response:
            saved = json.loads(response.read())
        assert saved["generations"] == 6
        assert saved["api"]["configured"] is True
        assert "sk-browser-test-1234" not in json.dumps(saved)

        with urllib.request.urlopen(
            f"{base}/solution-sessions", timeout=2
        ) as response:
            sessions = json.loads(response.read())
        assert sessions["sessions"][0]["session_id"] == "session-solutions"
        with urllib.request.urlopen(
            f"{base}/solution-sessions/session-solutions", timeout=2
        ) as response:
            timeline = json.loads(response.read())
        assert timeline["session"]["search"]["generations"] == 2
        assert timeline["turns"][0]["requirement"] == "Choose a feasible Pareto solution."
        assert timeline["turns"][0]["objective_series"][0]["name"] == "cost"
        assert timeline["turns"][0]["tss"]["slots"]["setup.py"].startswith("def build_problem")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_browser_uploads_feed_documents_and_tables_into_one_public_context(tmp_path: Path):
    store = StateStore(tmp_path / "state")
    server = ThreadingHTTPServer(
        ("127.0.0.1", 0), make_handler(store, max_upload_bytes=4096)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        base = f"http://127.0.0.1:{server.server_port}"

        def upload(filename: str, payload: bytes, media_type: str) -> dict[str, object]:
            request = urllib.request.Request(
                f"{base}/uploads?filename={urllib.parse.quote(filename)}",
                data=payload,
                method="POST",
                headers={"Content-Type": media_type},
            )
            with urllib.request.urlopen(request, timeout=2) as response:
                assert response.status == 201
                return json.loads(response.read())

        brief = upload(
            "clinic brief.md",
            "Choose a staffing plan while preserving night coverage.".encode(),
            "text/markdown",
        )
        demand = upload(
            "demand.csv",
            b"site_id,demand\nS01,12\nS02,8\n",
            "text/csv",
        )
        assert brief["kind"] == "document"
        assert demand["kind"] == "tables"

        service = _service(tmp_path)
        try:
            prepared = service.prepare_uploads(
                [str(brief["upload_id"]), str(demand["upload_id"])],
                inline_tables={"limits": [{"night_staff": 3}]},
            )
            record = service.store.load_prepared_data(prepared["prepared_data_id"])
            context = record["public_context"]
            assert context["documents"][0]["filename"] == "clinic brief.md"
            assert "night coverage" in context["documents"][0]["text"]
            assert context["tables"]["demand"][0] == {"site_id": "S01", "demand": 12}
            assert context["tables"]["limits"] == [{"night_staff": 3}]
            assert prepared["documents"][0]["truncated"] is False
        finally:
            service.close()

        bad_request = urllib.request.Request(
            f"{base}/uploads?filename=payload.exe",
            data=b"not allowed",
            method="POST",
            headers={"Content-Type": "application/octet-stream"},
        )
        with pytest.raises(urllib.error.HTTPError) as caught:
            urllib.request.urlopen(bad_request, timeout=2)
        assert caught.value.code == 415
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
