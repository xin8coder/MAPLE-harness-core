"""Stable JSON records for the accepted LiveOpt search state."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

from evo2.core.template_optimizer import Candidate, EvolutionResult, FitnessResult


def json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [json_safe(item) for item in value]
    if dataclasses.is_dataclass(value):
        return json_safe(dataclasses.asdict(value))
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return json_safe(item())
        except (TypeError, ValueError):
            pass
    return str(value)


def fitness_to_record(result: FitnessResult | None) -> dict[str, Any] | None:
    if result is None:
        return None
    return json_safe(
        {
            "scalar": result.scalar,
            "objectives": result.objectives,
            "feasible": result.feasible,
            "violations": result.violations,
            "base_scalar": result.base_scalar,
            "penalty": result.penalty,
            "solution": result.solution,
            "diagnostics": result.diagnostics,
        }
    )


def fitness_from_record(record: dict[str, Any] | None) -> FitnessResult | None:
    if record is None:
        return None
    return FitnessResult(
        scalar=float(record.get("scalar", math.inf)),
        objectives=[float(value) for value in record.get("objectives") or []],
        feasible=bool(record.get("feasible", False)),
        violations=dict(record.get("violations") or {}),
        base_scalar=(
            None if record.get("base_scalar") is None else float(record["base_scalar"])
        ),
        penalty=float(record.get("penalty") or 0.0),
        solution=dict(record.get("solution") or {}),
        diagnostics=dict(record.get("diagnostics") or {}),
    )


def candidate_to_record(candidate: Candidate) -> dict[str, Any]:
    return {
        "genome": json_safe(candidate.genome),
        "result": fitness_to_record(candidate.result),
        "rank": int(candidate.rank),
        "crowding_distance": json_safe(candidate.crowding_distance),
    }


def candidate_from_record(record: dict[str, Any]) -> Candidate:
    return Candidate(
        genome=dict(record.get("genome") or {}),
        result=fitness_from_record(record.get("result")),
        rank=int(record.get("rank", 10**9)),
        crowding_distance=float(record.get("crowding_distance") or 0.0),
    )


def evolution_to_record(result: EvolutionResult) -> dict[str, Any]:
    return {
        "best": candidate_to_record(result.best),
        "population": [candidate_to_record(item) for item in result.population],
        "archive": [candidate_to_record(item) for item in result.archive],
        "history": json_safe(result.history),
        "metadata": json_safe(result.metadata),
    }


def evolution_from_record(record: dict[str, Any]) -> EvolutionResult:
    return EvolutionResult(
        best=candidate_from_record(dict(record["best"])),
        population=[candidate_from_record(dict(item)) for item in record.get("population") or []],
        archive=[candidate_from_record(dict(item)) for item in record.get("archive") or []],
        history=list(record.get("history") or []),
        metadata=dict(record.get("metadata") or {}),
    )


def candidate_summary(candidate: Candidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    fitness = candidate.result
    return json_safe(
        {
            "genome": candidate.genome,
            "scalar": fitness.scalar if fitness else None,
            "objectives": fitness.objectives if fitness else [],
            "feasible": fitness.feasible if fitness else None,
            "violations": fitness.violations if fitness else {},
            "solution": fitness.solution if fitness else {},
        }
    )

