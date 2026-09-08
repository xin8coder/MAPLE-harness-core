from __future__ import annotations

import copy
import json
from dataclasses import replace
from typing import Any

from evo2.agents.liveopt_workbench_impl import ScaffoldProject
from evo2.core.template_optimizer import EvolutionResult, FitnessResult, SegmentSpec, coerce_fitness_result


MEMORY_VIEWS = {
    "full",
    "ledger_only",
    "accepted_only",
    "current_only",
    "oracle",
}

STATE_BINDING_QUERY_KINDS = {
    "lock_assignment",
    "preserve_demand_assignments",
    "preserve_resource_assignments",
}


def validate_memory_view(memory_view: str) -> str:
    normalized = str(memory_view or "full").strip().lower()
    if normalized not in MEMORY_VIEWS:
        raise ValueError(
            f"unsupported memory_view {memory_view!r}; expected one of {sorted(MEMORY_VIEWS)}"
        )
    return normalized


def memory_view_exposes_ledger(memory_view: str) -> bool:
    return validate_memory_view(memory_view) in {"full", "ledger_only"}


def memory_view_exposes_accepted(memory_view: str) -> bool:
    return validate_memory_view(memory_view) in {"full", "accepted_only", "oracle"}


def accepted_state_prompt_record(result: EvolutionResult | None) -> dict[str, Any]:
    """Return the committed public result exposed to the update controller.

    Population genomes and optimizer history remain private search state.  The
    prompt receives only the representative accepted solution and its public
    score, while the fixed binding materializer below can query the committed
    candidate genome when a typed binding explicitly requires it.
    """

    if result is None or result.best is None or result.best.result is None:
        return {"available": False}
    accepted = result.best
    fitness = accepted.result
    return {
        "available": True,
        "representative": {
            "solution": copy.deepcopy(fitness.solution or {}),
            "scalar": fitness.scalar,
            "objectives": list(fitness.objectives or []),
            "feasible": bool(fitness.feasible),
        },
    }


def normalize_state_binding_queries(payload: Any) -> list[dict[str, Any]]:
    """Normalize controller-emitted typed binding queries.

    Invalid records are rejected before they can affect the Workbench.  A
    caller that wants ablation failures to remain executable should catch the
    error and record an empty binding set, as ``materialize_state_bindings``
    does for missing accepted state.
    """

    if payload in (None, ""):
        return []
    if not isinstance(payload, list):
        raise ValueError("state_binding_queries must be a list")
    if len(payload) > 64:
        raise ValueError("state_binding_queries exceeds the 64-record limit")

    normalized: list[dict[str, Any]] = []
    for index, raw in enumerate(payload):
        if not isinstance(raw, dict):
            raise ValueError(f"state binding query {index} must be an object")
        kind = str(raw.get("kind") or "").strip()
        if kind not in STATE_BINDING_QUERY_KINDS:
            raise ValueError(
                f"state binding query {index} has unsupported kind {kind!r}; "
                f"expected one of {sorted(STATE_BINDING_QUERY_KINDS)}"
            )
        segment = str(raw.get("segment") or "").strip()
        if not segment:
            raise ValueError(f"state binding query {index} is missing segment")
        query: dict[str, Any] = {
            "binding_id": str(raw.get("binding_id") or f"binding_{index + 1:02d}"),
            "kind": kind,
            "segment": segment,
            "depends_on": sorted(
                {
                    str(item).strip()
                    for item in (raw.get("depends_on") or [])
                    if str(item).strip()
                }
            ),
        }
        if kind == "lock_assignment":
            assignments = raw.get("assignments")
            if not isinstance(assignments, dict) or not assignments:
                raise ValueError(
                    f"state binding query {index} lock_assignment requires non-empty assignments"
                )
            query["assignments"] = {
                str(demand): resource for demand, resource in assignments.items()
            }
        elif kind == "preserve_resource_assignments":
            resource_id = raw.get("resource_id")
            if resource_id in (None, ""):
                raise ValueError(
                    f"state binding query {index} preserve_resource_assignments requires resource_id"
                )
            query["resource_id"] = resource_id
        else:
            demands = raw.get("demands")
            if not isinstance(demands, list) or not demands:
                raise ValueError(
                    f"state binding query {index} preserve_demand_assignments requires non-empty demands"
                )
            query["demands"] = [str(demand) for demand in demands]
        normalized.append(query)
    return normalized


def materialize_state_bindings(
    queries: list[dict[str, Any]] | None,
    *,
    accepted_result: EvolutionResult | None,
    segments: list[SegmentSpec],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Resolve typed queries into concrete assignment locks.

    ``preserve_resource_assignments`` is deliberately evaluated by fixed code
    against the committed accepted candidate.  The language model resolves the
    requested relation and resource; it does not enumerate or invent the
    accepted assignments.  This separation makes ledger-only and
    accepted-only controls well defined.
    """

    normalized = normalize_state_binding_queries(queries or [])
    segment_by_name = {segment.name: segment for segment in segments}
    bindings: list[dict[str, Any]] = []
    errors: list[str] = []

    for query in normalized:
        segment_name = str(query["segment"])
        segment = segment_by_name.get(segment_name)
        if segment is None:
            errors.append(f"{query['binding_id']}: unknown segment {segment_name!r}")
            continue
        if segment.kind not in {"assignment", "optional_assignment"}:
            errors.append(
                f"{query['binding_id']}: segment {segment_name!r} has kind {segment.kind!r}, "
                "not assignment"
            )
            continue

        if query["kind"] == "lock_assignment":
            assignments = dict(query.get("assignments") or {})
        elif query["kind"] == "preserve_resource_assignments":
            if accepted_result is None or accepted_result.best is None:
                errors.append(f"{query['binding_id']}: accepted result is unavailable")
                continue
            genome = accepted_result.best.genome if isinstance(accepted_result.best.genome, dict) else {}
            accepted_assignments = genome.get(segment_name)
            if not isinstance(accepted_assignments, dict):
                errors.append(
                    f"{query['binding_id']}: accepted result has no assignment mapping for "
                    f"segment {segment_name!r}"
                )
                continue
            resource_id = query.get("resource_id")
            assignments = {
                str(demand): resource
                for demand, resource in accepted_assignments.items()
                if resource == resource_id or str(resource) == str(resource_id)
            }
            if not assignments:
                errors.append(
                    f"{query['binding_id']}: accepted result assigns no demand to resource "
                    f"{resource_id!r}"
                )
                continue
        else:
            if accepted_result is None or accepted_result.best is None:
                errors.append(f"{query['binding_id']}: accepted result is unavailable")
                continue
            genome = accepted_result.best.genome if isinstance(accepted_result.best.genome, dict) else {}
            accepted_assignments = genome.get(segment_name)
            if not isinstance(accepted_assignments, dict):
                errors.append(
                    f"{query['binding_id']}: accepted result has no assignment mapping for "
                    f"segment {segment_name!r}"
                )
                continue
            missing_demands = [
                demand for demand in query.get("demands") or [] if demand not in accepted_assignments
            ]
            if missing_demands:
                errors.append(
                    f"{query['binding_id']}: accepted result has no assignment for demands "
                    f"{missing_demands}"
                )
                continue
            assignments = {
                demand: accepted_assignments[demand] for demand in query.get("demands") or []
            }

        valid_demands = {str(item) for item in segment.demands}
        valid_resources = {str(item) for item in segment.resources}
        unknown_demands = sorted(set(assignments) - valid_demands)
        unknown_resources = sorted(
            {
                str(resource)
                for resource in assignments.values()
                if resource is not None and str(resource) not in valid_resources
            }
        )
        if unknown_demands or unknown_resources:
            errors.append(
                f"{query['binding_id']}: ids outside typed segment; "
                f"demands={unknown_demands}, resources={unknown_resources}"
            )
            continue
        bindings.append(
            {
                "binding_id": query["binding_id"],
                "kind": "lock_assignment",
                "segment": segment_name,
                "assignments": copy.deepcopy(assignments),
                "query_kind": query["kind"],
                "depends_on": list(query.get("depends_on") or []),
            }
        )

    return bindings, {
        "query_count": len(normalized),
        "materialized_count": len(bindings),
        "locked_assignment_count": sum(
            len(binding.get("assignments") or {}) for binding in bindings
        ),
        "errors": errors,
    }


def apply_state_bindings(
    project: ScaffoldProject,
    bindings: list[dict[str, Any]] | None,
) -> ScaffoldProject:
    """Return a project whose fixed evaluator enforces typed state bindings."""

    normalized = copy.deepcopy(list(bindings or []))
    if not normalized:
        return project
    base_evaluate = project.evaluate

    def evaluate(genome: dict[str, Any], data: dict[str, Any]) -> FitnessResult:
        result = coerce_fitness_result(base_evaluate(genome, data), genome)
        mismatches = state_binding_mismatches(genome, normalized)
        diagnostics = dict(result.diagnostics or {})
        diagnostics["state_binding_count"] = len(normalized)
        diagnostics["state_binding_mismatch_count"] = len(mismatches)
        if not mismatches:
            result.diagnostics = diagnostics
            return result

        violations = dict(result.violations or {})
        violations["state_binding_mismatch"] = len(mismatches)
        diagnostics["state_binding_mismatches"] = mismatches
        base_scalar = (
            float(result.base_scalar)
            if result.base_scalar is not None
            else float(result.scalar) - float(result.penalty or 0.0)
        )
        return FitnessResult.with_penalty(
            base_scalar,
            violations,
            objectives=list(result.objectives or []),
            solution=copy.deepcopy(result.solution or {}),
            diagnostics=diagnostics,
        )

    data = copy.deepcopy(project.data)
    data["state_bindings"] = normalized
    problem_spec = copy.deepcopy(project.problem_spec)
    problem_spec["state_bindings"] = normalized
    problem_spec["state_binding_signature"] = state_binding_signature(normalized)
    return replace(
        project,
        data=data,
        evaluate=evaluate,
        problem_spec=problem_spec,
    )


def state_binding_mismatches(
    genome: dict[str, Any], bindings: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for binding in bindings:
        if binding.get("kind") != "lock_assignment":
            mismatches.append(
                {
                    "binding_id": binding.get("binding_id"),
                    "error": f"unsupported materialized kind {binding.get('kind')!r}",
                }
            )
            continue
        segment_name = str(binding.get("segment") or "")
        observed = genome.get(segment_name)
        if not isinstance(observed, dict):
            mismatches.append(
                {
                    "binding_id": binding.get("binding_id"),
                    "segment": segment_name,
                    "error": "assignment segment is missing from genome",
                }
            )
            continue
        for demand, expected_resource in (binding.get("assignments") or {}).items():
            actual_resource = observed.get(demand)
            if actual_resource != expected_resource and str(actual_resource) != str(expected_resource):
                mismatches.append(
                    {
                        "binding_id": binding.get("binding_id"),
                        "segment": segment_name,
                        "demand": demand,
                        "expected": expected_resource,
                        "actual": actual_resource,
                    }
                )
    return mismatches


def state_binding_signature(bindings: list[dict[str, Any]] | None) -> str:
    return json.dumps(
        list(bindings or []),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
