"""Complete retained candidate sets and user preferences, without solver writes."""

from __future__ import annotations

import hashlib
import json
import math
import time
from typing import Any

from evo2.core.template_optimizer import Candidate, FitnessResult, nondominated_fronts

from .serialization import json_safe
from .store import StateStore
from .localization import localize_value


def solution_options(store: StateStore, session_id: str, turn: int | None = None) -> dict[str, Any]:
    snapshot = store.load_snapshot(session_id)
    latest = int(snapshot.get("turn") or 0)
    turn = latest if turn is None else turn
    if isinstance(turn, bool) or not isinstance(turn, int) or not 0 <= turn <= latest:
        raise ValueError("invalid optimization turn")
    event = store.load_event(session_id, turn)
    bundle = _optional_json(store, f"sessions/{session_id}/exports/t{turn:03d}/result_bundle.json")
    if bundle:
        population = bundle.get("final_population") or []
        archive = bundle.get("solution_set") or []
        best = bundle.get("best")
        names = (bundle.get("session") or {}).get("objective_names") or []
        coverage = "population_and_archive"
    elif turn == latest:
        result = snapshot.get("result") or {}
        population = [_flatten(row) for row in result.get("population") or []]
        archive = [_flatten(row) for row in result.get("archive") or []]
        best = _flatten(result.get("best") or {})
        names = (snapshot.get("problem_spec") or {}).get("objective_names") or []
        coverage = "population_and_archive"
    else:
        # Do not substitute a later population into an earlier problem state.
        accepted = event.get("accepted") or {}
        population, archive, best = [], accepted.get("archive") or [], accepted.get("best")
        names = accepted.get("objective_names") or []
        coverage = "retained_archive_only"

    rows: dict[str, dict[str, Any]] = {}
    for source, candidates in (("population", population), ("archive", archive), ("best", [best] if best else [])):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            values = candidate.get("objectives") or []
            identity = {key: candidate.get(key) for key in ("genome", "objectives", "solution")}
            key = hashlib.sha256(json.dumps(json_safe(identity), ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:20]
            if key in rows:
                rows[key]["sources"].append(source)
                continue
            rows[key] = {
                "id": key, "label": f"S{len(rows) + 1:03d}", "sources": [source],
                "objectives": values, "feasible": candidate.get("feasible") is True,
                "solution": candidate.get("solution") or {}, "genome": candidate.get("genome") or {},
                "violations": candidate.get("violations") or {}, "pareto": False,
            }
    width = max((len(row["objectives"]) for row in rows.values()), default=len(names))
    names = [str(names[index]) if index < len(names) else f"objective {index + 1}" for index in range(width)]
    valid = []
    for row in rows.values():
        values = row["objectives"]
        row["plottable"] = bool(width and len(values) == width and all(
            isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in values
        ))
        row["selectable"] = row["feasible"] and row["plottable"]
        if row["selectable"]:
            valid.append(Candidate(genome={"candidate_id": row["id"]}, result=FitnessResult(
                scalar=sum(values), objectives=values, feasible=True, violations={}, solution={},
            )))
    # FitnessResult objectives use the runtime's minimization convention.
    if valid:
        for candidate in nondominated_fronts(valid)[0]:
            rows[candidate.genome["candidate_id"]]["pareto"] = True
    preference = _optional_json(store, f"sessions/{session_id}/preferences/t{turn:03d}.json")
    localization = (bundle or {}).get("localization") or (snapshot.get("public_context") or {}).get("localization") or {}
    for row in rows.values():
        row["localized_solution"] = localize_value(row["solution"], localization)
    return json_safe({
        "session_id": session_id, "turn": turn, "latest_turn": latest,
        "title": snapshot.get("task_id") or session_id,
        "requirement": event.get("problem") if turn == 0 else event.get("natural_language_update"),
        "objective_names": names, "objective_directions": ["min"] * width,
        "coverage": coverage, "candidates": list(rows.values()), "preference": preference,
        "localization": localization,
        "counts": {"total": len(rows), "feasible": len(valid), "pareto": sum(row["pareto"] for row in rows.values())},
        "demo": snapshot.get("demo_metadata"),
    })


def save_preference(store: StateStore, session_id: str, turn: int, candidate_id: str) -> dict[str, Any]:
    if isinstance(turn, bool) or not isinstance(turn, int):
        raise ValueError("turn must be an integer")
    payload = solution_options(store, session_id, turn)
    if (payload.get("demo") or {}).get("validation") == "failed":
        raise ValueError("this demo did not pass business-rule validation")
    candidate = next((row for row in payload["candidates"] if row["id"] == candidate_id), None)
    if candidate is None:
        raise KeyError("candidate not found in this turn")
    if not candidate["selectable"]:
        raise ValueError("only feasible candidates with finite objectives can be selected")
    selection = {"session_id": session_id, "turn": turn, "candidate_id": candidate_id,
                 "label": candidate["label"], "selected_at": time.time(), "kind": "user_preference"}
    store.save_session_bytes(session_id, f"preferences/t{turn:03d}.json", json.dumps(selection).encode())
    return selection


def _flatten(record: dict[str, Any]) -> dict[str, Any]:
    if not record:
        return {}
    return {**(record.get("result") or {}), "genome": record.get("genome") or {}}


def _optional_json(store: StateStore, path: str) -> dict[str, Any] | None:
    try:
        value = json.loads(store.resolve_artifact(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    return value if isinstance(value, dict) else None
