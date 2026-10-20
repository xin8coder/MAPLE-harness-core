"""Independent, no-API checks against this example's public business rules."""
from __future__ import annotations

import math

from evo2.agents.liveopt_workbench_impl import ScaffoldTrace, compile_scaffold_project

from offline_client import FITNESS, SETUP


def validate_candidates(snapshot, payload):
    context = snapshot["public_context"]
    tables = context["tables"]
    team_ids = {row["id"] for row in tables["garment_export_teams"]}
    warehouse_ids = {row["id"] for row in tables["garment_export_warehouses"]}
    order_ids = {row["id"] for row in tables["garment_export_orders"]}
    names = {}
    for segment in snapshot["problem_spec"]["segments"]:
        if segment["kind"] == "assignment":
            resources = set(segment["resources"])
            if resources == team_ids:
                names["team"] = segment["name"]
            elif resources == warehouse_ids:
                names["warehouse"] = segment["name"]
        elif segment["kind"] == "permutation" and set(segment["values"]) == order_ids:
            names["sequence"] = segment["name"]
    if set(names) != {"team", "warehouse", "sequence"}:
        raise ValueError("Example validator needs explicit team/warehouse assignments and order permutation")
    reference = compile_scaffold_project("garment-public-check", context,
        {"setup.py": SETUP, "fitness.py": FITNESS}, ScaffoldTrace(model="public-rule-check-no-api"))
    # A displayed finish time rounded to six decimals changes weighted delay
    # by at most half a micro-hour per carton, including at the due-time kink.
    tolerances = [1e-6, sum(float(row["cartons"]) for row in tables["garment_export_orders"]) * 0.5e-6 + 1e-8]
    max_error = [0.0, 0.0]
    checked = 0
    for row in payload["candidates"]:
        genome = {key: row["genome"][value] for key, value in names.items()}
        expected = reference.evaluate(genome, reference.data)
        if expected["feasible"] != row["feasible"]:
            raise ValueError(f"{row['label']}: public capacity/work-hour feasibility mismatch")
        if len(row["objectives"]) != 2:
            raise ValueError("Expected separate total cost and late carton-hours")
        for i, (name, actual, target) in enumerate(zip(("total cost", "late carton-hours"), row["objectives"], expected["objectives"])):
            max_error[i] = max(max_error[i], abs(actual - target))
            if not math.isclose(actual, target, rel_tol=1e-12, abs_tol=tolerances[i]):
                raise ValueError(f"{row['label']}: {name} mismatch: generated={actual}, public rules={target}")
        checked += 1
    return {"status": "passed", "checked_candidates": checked,
            "checks": ["all-order assignments", "labor per worker", "overtime premium", "warehouse capacity",
                       "maximum shift length", "storage cost", "shipping cost", "late carton-hours"],
            "reference_source": "example public Excel rules", "api_calls": 0,
            "absolute_tolerance": tolerances, "maximum_absolute_error": max_error}
