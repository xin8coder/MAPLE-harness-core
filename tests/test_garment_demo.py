import copy
import importlib.util
from pathlib import Path

import pytest

from evo2.agents.liveopt_workbench_impl import ScaffoldTrace, compile_scaffold_project
from liveopt_dsh.compat import install_provider_compatibility


ROOT = Path(__file__).resolve().parents[1] / "examples" / "garment_export"


def module(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / f"{name}.py")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def test_demo_accounts_for_deadline_workers_and_capacity():
    install_provider_compatibility()
    tables = module("scenario").TABLES
    fixture = module("offline_client")
    context = {"tables": {"garment_export_" + key: copy.deepcopy(value) for key, value in tables.items()}}
    slots = {"setup.py": fixture.SETUP, "fitness.py": fixture.FITNESS}
    project = compile_scaffold_project("garment-test", context, slots, ScaffoldTrace(model="offline"))
    genome = {
        "team": {"DE-101": "A", "UK-204": "B", "FR-308": "B", "NL-410": "C", "US-512": "A", "AU-616": "A"},
        "warehouse": {"DE-101": "W1", "UK-204": "W2", "FR-308": "W2", "NL-410": "W2", "US-512": "W1", "AU-616": "W1"},
        "sequence": ["DE-101", "FR-308", "UK-204", "NL-410", "US-512", "AU-616"],
    }
    first = project.evaluate(genome, project.data)
    assert first["feasible"]
    assert first["objectives"][0] == pytest.approx(sum(first["solution"]["cost_breakdown"].values()))
    assert sum(row["used"] for row in first["solution"]["warehouse_plan"]) == 355
    orders = {row["order_id"]: row for row in first["solution"]["order_plan"]}
    assert orders["UK-204"]["arrival_hour"] == pytest.approx(4.15)
    assert orders["UK-204"]["late_hours"] == 0
    context["tables"]["garment_export_orders"][1]["due_hour"] = 4.5
    context["tables"]["garment_export_teams"][1]["workers"] = 3
    updated = compile_scaffold_project("garment-test", context, slots, ScaffoldTrace(model="offline"))
    second = updated.evaluate(genome, updated.data)
    assert second["feasible"]
    rows = {row["order_id"]: row for row in second["solution"]["order_plan"]}
    assert rows["UK-204"]["arrival_hour"] == pytest.approx(5.25)
    assert second["objectives"][1] - first["objectives"][1] == pytest.approx(60)
    assert second["objectives"][0] - first["objectives"][0] == pytest.approx(-16)
    overloaded = copy.deepcopy(genome)
    overloaded["warehouse"] = {key: "W1" for key in genome["warehouse"]}
    assert not updated.evaluate(overloaded, updated.data)["feasible"]


def test_demo_validation_detects_underpriced_labor(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT))
    from validate_results import validate_candidates
    install_provider_compatibility()
    fixture = module("offline_client")
    context = {"tables": {"garment_export_" + key: copy.deepcopy(value) for key, value in module("scenario").TABLES.items()}}
    project = compile_scaffold_project("garment-validation", context,
        {"setup.py": fixture.SETUP, "fitness.py": fixture.FITNESS}, ScaffoldTrace(model="offline"))
    ids = [row["id"] for row in context["tables"]["garment_export_orders"]]
    genome = {"sequence": ids, "team": dict(zip(ids, ["A", "B", "B", "C", "A", "A"])),
              "warehouse": dict(zip(ids, ["W1", "W2", "W2", "W2", "W1", "W1"]))}
    result = project.evaluate(genome, project.data)
    candidate = {"label": "S001", "genome": genome, **result}
    snapshot = {"public_context": context, "problem_spec": project.problem_spec}
    assert validate_candidates(snapshot, {"candidates": [candidate]})["status"] == "passed"
    candidate["objectives"][0] -= 500
    with pytest.raises(ValueError, match="total cost mismatch"):
        validate_candidates(snapshot, {"candidates": [candidate]})
