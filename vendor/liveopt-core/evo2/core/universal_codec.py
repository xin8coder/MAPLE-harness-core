from __future__ import annotations

import copy
import uuid
from typing import Any

from evo2.core.artifacts import ArtifactBundle, UniversalOptimizationArtifact
from evo2.core.population import Individual
from evo2.core.solution import Solution


def wrap_solution(raw: dict[str, Any], prefix: str = "artifact") -> Solution:
    if not isinstance(raw, dict):
        raise ValueError("generated artifact returned a non-dict solution")
    objective = raw.get("objective_value")
    feasible = bool(raw.get("feasible", False))
    violations = raw.get("violations", {})
    metadata = raw.get("metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    return Solution(
        solution_id=str(raw.get("solution_id") or f"{prefix}_{uuid.uuid4().hex[:8]}"),
        assignments=copy.deepcopy(raw),
        objective_value=float(objective) if isinstance(objective, int | float) else None,
        feasible=feasible,
        violations=violations if isinstance(violations, dict) else {},
        metadata={"encoding": "universal_artifact_dict", **metadata},
    )


def unwrap_solution(solution: Solution | dict[str, Any]) -> dict[str, Any]:
    if isinstance(solution, Solution):
        return copy.deepcopy(solution.assignments or {})
    if isinstance(solution, dict):
        return copy.deepcopy(solution)
    raise ValueError("solution must be a Solution or dict")


class UniversalDecoder:
    """Domain-neutral decoder backed by LLM-generated artifacts."""

    def __init__(self, artifact: UniversalOptimizationArtifact):
        self.artifact = artifact

    @classmethod
    def from_context(cls, context) -> "UniversalDecoder":
        artifact = None
        if getattr(context, "memory", None):
            artifact = context.memory.get("universal_artifact")
        if artifact is None:
            artifact = getattr(context, "universal_artifact", None)
        if artifact is None:
            raise ValueError("UniversalDecoder requires context.memory['universal_artifact']")
        return cls(artifact)

    def candidate_at(self, index: int, memory: dict[str, Any] | None = None, prefix: str = "candidate") -> Solution:
        genome = self.artifact.genome_at(memory or {}, index)
        raw = self.artifact.decode(genome, memory or {})
        raw = self.artifact.repair(raw, memory or {})
        return wrap_solution(raw, prefix)

    def repair_solution(self, solution: Solution | dict[str, Any], memory: dict[str, Any] | None = None, prefix: str = "repair") -> Solution:
        raw = self.artifact.repair(unwrap_solution(solution), memory or {})
        return wrap_solution(raw, prefix)

    def mutate_solution(self, solution: Solution | dict[str, Any], memory: dict[str, Any] | None = None, prefix: str = "mut") -> Solution:
        raw = self.artifact.mutate(unwrap_solution(solution), memory or {})
        raw = self.artifact.repair(raw, memory or {})
        return wrap_solution(raw, prefix)

    def crossover(self, parent_a: Solution | dict[str, Any], parent_b: Solution | dict[str, Any], memory: dict[str, Any] | None = None, prefix: str = "cross") -> Solution:
        raw = self.artifact.crossover(unwrap_solution(parent_a), unwrap_solution(parent_b), memory or {})
        raw = self.artifact.repair(raw, memory or {})
        return wrap_solution(raw, prefix)


class UniversalArtifactFitness:
    def evaluate(self, solution: Solution, context) -> float:
        artifact = context.memory.get("universal_artifact")
        if artifact is None:
            raise ValueError("UniversalArtifactFitness requires context.memory['universal_artifact']")
        value = artifact.objective(unwrap_solution(solution), _artifact_memory(context))
        solution.metadata = dict(solution.metadata or {})
        solution.metadata["objective_raw"] = copy.deepcopy(value)
        return objective_to_scalar(value)


def objective_to_scalar(value: Any) -> float:
    if isinstance(value, dict):
        scalar = value.get("scalar")
        if scalar is None:
            objectives = value.get("objectives", [])
            if isinstance(objectives, list):
                scalar = sum(float(v) for v in objectives)
        if scalar is None:
            raise ValueError("multi-objective objective dict must include scalar or objectives list")
        value = scalar
    return float(value)


class UniversalArtifactVerifier:
    def verify(self, ir, solution: Solution, context) -> dict[str, Any]:
        artifact = context.memory.get("universal_artifact")
        if artifact is None:
            raise ValueError("UniversalArtifactVerifier requires context.memory['universal_artifact']")
        memory = _artifact_memory(context)
        result = artifact.verifier(unwrap_solution(solution), memory)
        if not isinstance(result, dict) or "feasible" not in result:
            raise ValueError("generated verifier must return {'feasible': bool, 'violations': dict}")
        violations = result.get("violations", {})
        if not isinstance(violations, dict):
            violations = {"invalid_violations": violations}
        coverage_violations = _coverage_violations(unwrap_solution(solution), artifact, memory)
        violations = {**violations, **coverage_violations}
        feasible = bool(result.get("feasible")) and not coverage_violations
        return {"feasible": feasible, "violations": violations, **{k: v for k, v in result.items() if k not in {"feasible", "violations"}}}


def individual_from_solution(solution: Solution, prefix: str) -> Individual:
    sol = copy.deepcopy(solution)
    sol.solution_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return Individual(individual_id=f"ind_{sol.solution_id}", solution=sol, metadata={"source": prefix})


def bundle_summary(bundle: ArtifactBundle) -> dict[str, Any]:
    return {
        "domain_label": bundle.contract.domain_label,
        "problem_summary": bundle.contract.problem_summary,
        "solution_schema": bundle.contract.solution_schema,
        "objective": bundle.contract.objective,
        "constraints": bundle.contract.constraints,
        "artifact_types": sorted(bundle.artifacts),
        "solver_recommendation": bundle.solver_recommendation,
        "has_linear_program_spec": bool(bundle.linear_program_spec),
    }


def _artifact_memory(context) -> dict[str, Any]:
    memory = dict(getattr(context, "memory", {}) or {})
    memory.pop("universal_artifact", None)
    return memory


def _coverage_violations(solution: dict[str, Any], artifact: UniversalOptimizationArtifact, memory: dict[str, Any] | None = None) -> dict[str, Any]:
    spec = artifact.encoding_spec(memory or {})
    expected = spec.get("values")
    if not isinstance(expected, list) or not expected:
        return {}
    expected_set = set(expected)
    observed = _solution_decision_ids(solution, artifact, expected_set)
    unassigned = _collect_unresolved_ids(solution, artifact)
    if not observed and not unassigned:
        return {"coverage_empty_solution": {"expected_count": len(expected)}}
    missing = sorted(expected_set - observed - unassigned, key=str)
    unknown = sorted((observed | unassigned) - expected_set, key=str)
    violations: dict[str, Any] = {}
    if missing:
        violations["coverage_missing_decisions"] = missing[:20]
    if unknown:
        violations["coverage_unknown_decisions"] = unknown[:20]
    return violations


def _solution_field_aliases(artifact: UniversalOptimizationArtifact | None) -> dict[str, str]:
    if artifact is None:
        return {}
    contract = getattr(artifact, "contract", {}) or {}
    if not isinstance(contract, dict):
        return {}
    schema = contract.get("solution_schema") if isinstance(contract.get("solution_schema"), dict) else {}
    aliases = schema.get("field_aliases") if isinstance(schema.get("field_aliases"), dict) else {}
    metadata = contract.get("metadata") if isinstance(contract.get("metadata"), dict) else {}
    interface = metadata.get("artifact_interface") if isinstance(metadata.get("artifact_interface"), dict) else {}
    interface_aliases = interface.get("canonical_solution_fields") if isinstance(interface.get("canonical_solution_fields"), dict) else {}
    fields: dict[str, str] = {}
    fields.update({str(k): str(v) for k, v in aliases.items() if v})
    fields.update({str(k): str(v) for k, v in interface_aliases.items() if v})
    return fields


def _first_roster_assignment_dict(solution: dict[str, Any]) -> dict[str, Any] | None:
    for key, value in solution.items():
        if key in {"genome", "unassigned", "leftover"} or not isinstance(value, dict):
            continue
        if any(isinstance(item_key, str) and "|" in item_key for item_key in value.keys()):
            return value
    return None


def _solution_decision_ids(
    solution: dict[str, Any],
    artifact: UniversalOptimizationArtifact | None = None,
    expected_set: set[Any] | None = None,
) -> set[Any]:
    fields = _solution_field_aliases(artifact)
    field_names = {str(key) for key in fields.keys()} | {str(value) for value in fields.values() if value}
    observed = _collect_ids(solution.get("routes")) | set(solution.get("assigned", [])) | set(solution.get("served", []))
    selection_keys = [
        "selected_items",
        "selected_decisions",
        "items",
        "selected",
        "visited",
        "completed",
        "scheduled",
    ]
    for key in selection_keys + sorted(field_names & {"selected_items", "selected_decisions", "items", "selected"}):
        value = solution.get(key)
        if isinstance(value, list):
            observed |= set(value)
    assignment_keys = [
        "assignments",
        "assignment",
        "placements",
        "allocations",
        "decision_assignments",
    ]
    for alias in [fields.get("assignments"), fields.get("placements"), fields.get("allocations")]:
        if alias:
            assignment_keys.insert(0, str(alias))
    for assignment_key in dict.fromkeys(assignment_keys):
        assignments = solution.get(assignment_key)
        if isinstance(assignments, dict):
            observed |= _assignment_decision_ids(assignments, expected_set)
    for sequence_key in dict.fromkeys(
        [
            fields.get("schedule") or "",
            fields.get("timeline") or "",
            "schedule",
            "timeline",
            "machine_sequences",
            "sequences",
        ]
    ):
        if not sequence_key:
            continue
        sequence = solution.get(sequence_key)
        if isinstance(sequence, list):
            for item in sequence:
                if isinstance(item, dict):
                    for key in ["operation_id", "job_id", "task_id", "id"]:
                        value = item.get(key)
                        if value is not None:
                            observed.add(value)
                            break
                else:
                    observed |= _collect_ids(item)
    return observed


def _assignment_decision_ids(assignments: dict[Any, Any], expected_set: set[Any] | None = None) -> set[Any]:
    keys = set(assignments.keys())
    if not expected_set:
        return keys
    value_ids: set[Any] = set()
    for value in assignments.values():
        value_ids |= _collect_scalar_ids(value)
    key_hits = keys & expected_set
    value_hits = value_ids & expected_set
    if value_hits and (not key_hits or len(value_hits) > len(key_hits)):
        return value_ids
    return keys


def _collect_unresolved_ids(solution: dict[str, Any], artifact: UniversalOptimizationArtifact | None = None) -> set[Any]:
    fields = _solution_field_aliases(artifact)
    unresolved: set[Any] = set()
    keys = [
        fields.get("unassigned") or "",
        fields.get("unscheduled") or "",
        fields.get("leftover") or "",
        "unassigned",
        "unassigned_orders",
        "unassigned_operations",
        "unscheduled",
        "unscheduled_operations",
        "leftover",
    ]
    for key in dict.fromkeys(k for k in keys if k):
        value = solution.get(key)
        if isinstance(value, list):
            unresolved |= set(value)
    return unresolved


def _collect_ids(value: Any) -> set[Any]:
    ids: set[Any] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"vehicle", "vehicle_id", "route_id", "route", "resource", "machine", "worker"}:
                continue
            ids |= _collect_ids(child)
    elif isinstance(value, list):
        for child in value:
            ids |= _collect_ids(child)
    elif isinstance(value, (str, int)):
        ids.add(value)
    return ids


def _collect_scalar_ids(value: Any) -> set[Any]:
    ids: set[Any] = set()
    if isinstance(value, dict):
        for child in value.values():
            ids |= _collect_scalar_ids(child)
    elif isinstance(value, list):
        for child in value:
            ids |= _collect_scalar_ids(child)
    elif isinstance(value, (str, int)):
        ids.add(value)
    return ids
