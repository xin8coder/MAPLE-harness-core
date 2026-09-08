from __future__ import annotations

import json
from pathlib import Path

import pytest

from liveopt_dsh.config import ServiceConfig
from liveopt_dsh.service import LiveOptService

from simulated_deepseek import SimulatedClientFactory


def _service(tmp_path: Path) -> tuple[LiveOptService, SimulatedClientFactory]:
    factory = SimulatedClientFactory()
    service = LiveOptService(
        ServiceConfig(
            state_dir=tmp_path / "state",
            workspace_root=tmp_path,
            max_workers=2,
            max_result_archive=100,
        ),
        client_factory=factory,
    )
    return service, factory


def _solve(
    service: LiveOptService,
    *,
    problem: str,
    prepared_data_id: str,
    solver_preference: str,
    population_size: int = 18,
    generations: int = 6,
) -> tuple[str, dict]:
    started = service.submit_start(
        problem=problem,
        prepared_data_id=prepared_data_id,
        provider="deepseek",
        model="deepseek-v4-flash",
        solver_preference=solver_preference,
        population_size=population_size,
        generations=generations,
        seed=7,
        archive_limit=100,
        max_repairs=3,
    )
    job = service.wait_for_job(started["job_id"], timeout_seconds=20)
    assert job["status"] == "succeeded", job.get("error")
    assert job["result"]["accepted"]["best"]["feasible"] is True
    return started["session_id"], job


def test_offline_simulated_deepseek_covers_industries_objectives_encodings_and_formats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    def no_network(*_args, **_kwargs):
        raise AssertionError("offline requirement matrix reached the network")

    monkeypatch.setattr("urllib.request.urlopen", no_network)
    (tmp_path / "healthcare.json").write_text(
        json.dumps(
            {
                "programs": [
                    {"id": "H1", "cost": 6, "health_gain": 11},
                    {"id": "H2", "cost": 5, "health_gain": 8},
                    {"id": "H3", "cost": 4, "health_gain": 7},
                ],
                "policy": [{"budget": 10}],
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "cities.csv").write_text(
        "id,x,y\nC1,0,0\nC2,2,0\nC3,2,2\nC4,0,2\nC5,1,3\n",
        encoding="utf-8",
    )
    (tmp_path / "periods.tsv").write_text(
        "period\tdemand\tmax_order\torder_cost\tholding_cost\tshortage_cost\n"
        "1\t5\t9\t2.0\t0.4\t5.0\n2\t8\t10\t2.2\t0.4\t5.0\n3\t4\t8\t2.1\t0.5\t6.0\n",
        encoding="utf-8",
    )
    (tmp_path / "projects.jsonl").write_text(
        "\n".join(
            json.dumps(row)
            for row in [
                {"id": "P1", "cost": 4, "public_value": 8},
                {"id": "P2", "cost": 6, "public_value": 11},
                {"id": "P3", "cost": 3, "public_value": 5},
                {"id": "P4", "cost": 5, "public_value": 9},
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    service, factory = _service(tmp_path)
    try:
        healthcare = service.prepare_data([{"path": "healthcare.json"}])
        healthcare_id, _ = _solve(
            service,
            problem=(
                "Healthcare program selection: choose public programs to maximize total "
                "health gain under the stated budget. This is a formal exact MILP request."
            ),
            prepared_data_id=healthcare["prepared_data_id"],
            solver_preference="exact",
        )
        healthcare_snapshot = service.store.load_snapshot(healthcare_id)
        assert healthcare_snapshot["problem_spec"]["solver_mode"] == "linear_mip"
        assert healthcare_snapshot["result"]["metadata"]["selection"] == "linear_mip"

        routing = service.prepare_data(
            [{"path": "cities.csv", "table_name": "cities", "id_column": "id"}]
        )
        routing_id, _ = _solve(
            service,
            problem=(
                "Plan a cold-chain delivery route as one Hamiltonian cycle. Minimize the "
                "Euclidean route length over all public cities."
            ),
            prepared_data_id=routing["prepared_data_id"],
            solver_preference="evolutionary",
        )
        assert [
            segment["kind"]
            for segment in service.store.load_snapshot(routing_id)["problem_spec"]["segments"]
        ] == ["permutation"]

        energy = service.prepare_data(
            inline_tables={
                "devices": [
                    {"id": "G1", "min_kw": 0, "max_kw": 6, "cost_per_kwh": 2.0, "emission_factor": 0.8},
                    {"id": "G2", "min_kw": 0, "max_kw": 7, "cost_per_kwh": 2.8, "emission_factor": 0.3},
                    {"id": "G3", "min_kw": 0, "max_kw": 5, "cost_per_kwh": 3.4, "emission_factor": 0.1},
                ],
                "policy": [{"demand_kw": 9}],
            }
        )
        energy_id, _ = _solve(
            service,
            problem=(
                "Microgrid dispatch in conversational form: meet demand while trading off "
                "operating cost and nonlinear emissions. Return a Pareto set."
            ),
            prepared_data_id=energy["prepared_data_id"],
            solver_preference="evolutionary",
            population_size=24,
            generations=8,
        )
        energy_snapshot = service.store.load_snapshot(energy_id)
        assert energy_snapshot["problem_spec"]["solver_mode"] == "moea"
        assert [segment["kind"] for segment in energy_snapshot["problem_spec"]["segments"]] == [
            "real_vector"
        ]
        energy_export = service.export_results(energy_id)
        assert [series["name"] for series in energy_export["objective_series"]] == [
            "operating_cost",
            "emissions",
        ]
        assert len(energy_export["population_preview"]) == 24
        assert energy_export["pareto_preview"]

        inventory = service.prepare_data(
            [{"path": "periods.tsv", "table_name": "periods", "id_column": "period"}],
            inline_tables={"policy": [{"initial_inventory": 2}]},
        )
        inventory_id, _ = _solve(
            service,
            problem=(
                "零售库存补货：按期决定整数订货量，综合最小化订货、持有和缺货成本。"
                " This inventory request uses the public periods table."
            ),
            prepared_data_id=inventory["prepared_data_id"],
            solver_preference="evolutionary",
        )
        assert [
            segment["kind"]
            for segment in service.store.load_snapshot(inventory_id)["problem_spec"]["segments"]
        ] == ["int_vector"]

        budget = service.prepare_data(
            [{"path": "projects.jsonl", "table_name": "projects", "id_column": "id"}],
            inline_tables={"policy": [{"budget": 10}]},
        )
        budget_id, _ = _solve(
            service,
            problem=(
                "公共预算 public budget allocation: choose a subset of projects to maximize "
                "public_value without exceeding the public budget."
            ),
            prepared_data_id=budget["prepared_data_id"],
            solver_preference="evolutionary",
        )
        assert [
            segment["kind"]
            for segment in service.store.load_snapshot(budget_id)["problem_spec"]["segments"]
        ] == ["binary_vector"]

        assert len(factory.clients) == 5
        assert all(client.calls for client in factory.clients)
        assert all(
            call["temperature"] == 0.0
            for client in factory.clients
            for call in client.calls
        )
    finally:
        service.close()


def test_offline_cnc_resource_failure_is_data_only_and_keeps_mixed_pareto_search(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("offline CNC regression reached the network")
        ),
    )
    (tmp_path / "cnc.csv").write_text(
        "job_id,family,release_h,due_h,priority_w,setup_level,p_M1_h,p_M2_h,p_M3_h,eligible_M1,eligible_M2,eligible_M3\n"
        "J1,A,0,8,2,1,2.0,2.4,2.8,1,1,1\n"
        "J2,B,0,9,1,2,2.5,2.0,2.7,1,1,1\n"
        "J3,A,1,10,3,1,2.2,2.6,2.1,1,1,1\n"
        "J4,C,1,12,2,3,3.0,2.8,2.4,1,1,1\n"
        "J5,B,2,13,1,2,2.7,2.3,2.6,1,1,1\n",
        encoding="utf-8",
    )
    service, factory = _service(tmp_path)
    try:
        prepared = service.prepare_data(
            [{"path": "cnc.csv", "table_name": "cnc_orders", "id_column": "job_id"}],
            inline_tables={
                "machines": [
                    {"id": "M1", "power_kw": 7.0, "setup_rate": 0.45, "active": True},
                    {"id": "M2", "power_kw": 9.2, "setup_rate": 0.35, "active": True},
                    {"id": "M3", "power_kw": 5.6, "setup_rate": 0.55, "active": True},
                ]
            },
            column_groups=[
                {
                    "source_table": "cnc_orders",
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
        session_id, _ = _solve(
            service,
            problem=(
                "Bi-objective nonlinear flexible parallel-machine CNC scheduling. Assign "
                "each public order to one eligible machine and choose processing sequences; "
                "minimize energy and weighted tardiness as a Pareto task."
            ),
            prepared_data_id=prepared["prepared_data_id"],
            solver_preference="evolutionary",
            population_size=30,
            generations=8,
        )
        before = service.inspect(session_id=session_id, view="workbench")
        assert [segment["kind"] for segment in service.store.load_snapshot(session_id)["problem_spec"]["segments"]] == [
            "assignment",
            "permutation",
        ]
        assert "'M1'" not in before["slots"]["setup.py"]
        assert '"M1"' not in before["slots"]["setup.py"]

        queued = service.submit_update(
            session_id=session_id,
            update_id="t001",
            update=(
                "Machine M1 is unavailable. Disable M1 and every M1 eligibility record in "
                "the public tables; keep both objectives and the existing encoding logic."
            ),
        )
        job = service.wait_for_job(queued["job_id"], timeout_seconds=20)
        assert job["status"] == "succeeded", job.get("error")
        assert job["result"]["accepted"]["best"]["feasible"] is True
        after = service.inspect(session_id=session_id, view="workbench")
        assert after["slots"]["setup.py"] == before["slots"]["setup.py"]
        machines = after["public_context"]["tables"]["machines"]
        assert next(row for row in machines if row["id"] == "M1")["active"] is False
        m1_options = [
            row
            for row in after["public_context"]["tables"]["job_machine_options"]
            if row["machine_id"] == "M1"
        ]
        assert m1_options and all(row["eligible"] is False for row in m1_options)
        trace = service.inspect(session_id=session_id, view="trace", turn=1)
        assert trace["impact"]["data_update"] is True
        assert trace["impact"]["patch_setup"] is False
        assert trace["impact"]["patch_fitness"] is False
        assert not any(
            "setup.py" in response and "def build_problem" in response
            for response in trace["patch_trace"]["raw_responses"][2:]
        )
        exported = service.export_results(session_id)
        assert [series["name"] for series in exported["objective_series"]] == [
            "energy",
            "weighted_tardiness",
        ]
        assert exported["population_count"] == 30
        assert exported["pareto_preview"]
        assert len(factory.clients) == 1
    finally:
        service.close()
