from __future__ import annotations

import ast
import copy
import json
import math
import random
import re
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from evo2.agents.code_slots import merge_code_slots, parse_code_slots
from evo2.agents.llm_client import create_llm_client, is_llm_quota_limit_error
from evo2.agents.liveopt_state_binding import (
    accepted_state_prompt_record,
    apply_state_bindings,
    materialize_state_bindings,
    memory_view_exposes_accepted,
    memory_view_exposes_ledger,
    normalize_state_binding_queries,
    validate_memory_view,
)
from evo2.agents.liveopt_workbench_impl import ScaffoldProject, ScaffoldTrace, compile_scaffold_project
from evo2.agents.semantic_restart_gate import LiveOptSemanticRestartGate, SemanticRestartDecision
from evo2.core.template_optimizer import (
    Candidate,
    EvolutionConfig,
    EvolutionResult,
    SegmentSpec,
    coerce_fitness_result,
    mutate_genome,
    nsga2_select,
)


RESTART_SKILLS = {
    "adaptive_mix_v1",
    "full_restart_v1",
    "warm_restart_v1",
    "population_transfer_v1",
}

# A restart decision should answer whether the old search state is still a
# useful basin, not whether objective values merely changed their offset or
# scale.  These thresholds define a public, domain-independent regime
# replacement: a substantial fraction of the compiled public state changed or
# the typed decision support/objective dimension changed. Retained-candidate
# rank reversal is recorded only as corroboration because penalty rankings can
# vary by seed. The minimum fact count prevents one edited scalar in a tiny
# table from looking like a wholesale regime replacement.
REGIME_DATA_CHURN_THRESHOLD = 0.15
REGIME_DATA_CHANGED_FACTS_MIN = 8
REGIME_SEGMENT_DISTANCE_THRESHOLD = 0.20
REGIME_RANK_DISRUPTION_THRESHOLD = 0.60

# Traditional DMOEAs commonly re-evaluate a small, fixed fraction of the
# population after an environmental change.  The landscape control below
# follows that protocol and deliberately remains separate from LiveOpt's
# semantic selector.  Following severity estimators that compare each
# objective before and after a change, it uses the mean absolute relative
# change of each objective and then takes the maximum across objectives.  The
# constants are fixed without a reference archive or HV/IGD.
LANDSCAPE_SENSOR_FRACTION = 0.10
LANDSCAPE_MIN_SENSORS = 4
LANDSCAPE_DISPLACEMENT_THRESHOLD = 0.50
LANDSCAPE_FEASIBILITY_LOSS_THRESHOLD = 0.50

# Opaque, instance-indexed identifiers are unsafe to embed in generated slot
# code.  Stable schema categories such as ``day``/``night`` are not instance
# entities and remain legal literals.  Keep this contract aligned with the
# offline slot audit.
INSTANCE_ENTITY_LITERAL = re.compile(r"^(?:[A-Z]{1,4}\d{1,4}|[A-Z]\d{1,3}_\d{1,3}|B\d+_\d+)$")


@dataclass(frozen=True)
class DynamicUpdateImpact:
    data_update: bool = False
    patch_setup: bool = False
    patch_fitness: bool = False
    restart_skill: str = "full_restart_v1"
    reason: str = ""
    raw: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "DynamicUpdateImpact":
        restart_skill = str(payload.get("restart_skill") or "full_restart_v1")
        if restart_skill not in RESTART_SKILLS:
            raise ValueError(f"unsupported restart_skill: {restart_skill}")
        return cls(
            data_update=bool(payload.get("data_update", False)),
            patch_setup=bool(payload.get("patch_setup", False)),
            patch_fitness=bool(payload.get("patch_fitness", False)),
            restart_skill=restart_skill,
            reason=str(payload.get("reason") or ""),
            raw=dict(payload),
        )

    def with_restart_skill(self, restart_skill: str, *, reason: str | None = None) -> "DynamicUpdateImpact":
        if restart_skill not in RESTART_SKILLS:
            raise ValueError(f"unsupported restart_skill: {restart_skill}")
        raw = dict(self.raw)
        raw["original_restart_skill"] = self.restart_skill
        raw["restart_skill"] = restart_skill
        raw["restart_policy_override"] = True
        override_reason = reason or f"forced restart ablation: {restart_skill}"
        return replace(
            self,
            restart_skill=restart_skill,
            reason=(self.reason + " | " + override_reason).strip(" |"),
            raw=raw,
        )


@dataclass
class DynamicScaffoldStage:
    update_id: str
    natural_language_update: str
    impact: DynamicUpdateImpact
    project: ScaffoldProject
    result: EvolutionResult
    initial_genomes: list[dict[str, Any]]
    restart_metadata: dict[str, Any]
    patch_trace: ScaffoldTrace
    latency_seconds: float

    def to_record(self) -> dict[str, Any]:
        return {
            "update_id": self.update_id,
            "natural_language_update": self.natural_language_update,
            "impact": self.impact.__dict__,
            "restart_metadata": self.restart_metadata,
            "initial_seed_count": len(self.initial_genomes),
            "setup_code": self.project.setup_code,
            "fitness_code": self.project.fitness_code,
            "segments": [segment.__dict__ for segment in self.project.segments],
            "best": _candidate_record(self.result.best),
            "archive_count": len(self.result.archive),
            "population_count": len(self.result.population),
            "history": self.result.history,
            "latency_seconds": self.latency_seconds,
            "patch_trace": {
                "model": self.patch_trace.model,
                "prompts": self.patch_trace.prompts,
                "raw_responses": self.patch_trace.raw_responses,
                "usage": self.patch_trace.usage,
                "errors": self.patch_trace.errors,
                "latency_seconds": self.patch_trace.latency_seconds,
            },
        }


@dataclass(frozen=True)
class ObjectiveSpaceShift:
    """Public evidence used by the warm-versus-full regime selector.

    This record never launches a trial optimizer or evaluates a held-out
    reference. It compares compiled public state and typed decision support,
    then re-evaluates accepted old candidates under the patched public
    Workbench. Absolute objective location/scale changes remain diagnostics;
    they do not by themselves imply that historical search state is harmful.
    """

    sample_count: int = 0
    segment_distance: float = 1.0
    direct_feasible_ratio: float = 0.0
    current_objective_count: int = 0
    rank_correlation: float | None = None
    median_relative_scalar_shift: float | None = None
    objective_dimension_changed: bool = False
    objective_center_shift: float = 0.0
    objective_scale_shift: float = 0.0
    objective_rank_disruption: float = 0.0
    public_state_churn: float = 0.0
    public_state_changed_fact_count: int = 0
    public_state_union_fact_count: int = 0
    objective_space_shift: float = 1.0
    fresh_population_ratio: float = 0.5
    history_population_ratio: float = 0.5
    selected_restart_skill: str = "warm_restart_v1"
    selected_response_function: str = "public_regime_warm_full_selector"
    large_change_signals: tuple[str, ...] = ()
    reason: str = "no previous public population"

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "ObjectiveSpaceShift":
        fields = cls.__dataclass_fields__
        return cls(**{key: payload[key] for key in fields if key in payload})

    def to_record(self) -> dict[str, Any]:
        return {
            "sample_count": self.sample_count,
            "segment_distance": round(float(self.segment_distance), 6),
            "direct_feasible_ratio": round(float(self.direct_feasible_ratio), 6),
            "current_objective_count": self.current_objective_count,
            "rank_correlation": None if self.rank_correlation is None else round(float(self.rank_correlation), 6),
            "median_relative_scalar_shift": None
            if self.median_relative_scalar_shift is None
            else round(float(self.median_relative_scalar_shift), 6),
            "objective_dimension_changed": self.objective_dimension_changed,
            "objective_center_shift": round(float(self.objective_center_shift), 6),
            "objective_scale_shift": round(float(self.objective_scale_shift), 6),
            "objective_rank_disruption": round(float(self.objective_rank_disruption), 6),
            "public_state_churn": round(float(self.public_state_churn), 6),
            "public_state_changed_fact_count": self.public_state_changed_fact_count,
            "public_state_union_fact_count": self.public_state_union_fact_count,
            "objective_space_shift": round(float(self.objective_space_shift), 6),
            "fresh_population_ratio": round(float(self.fresh_population_ratio), 6),
            "history_population_ratio": round(float(self.history_population_ratio), 6),
            "selected_restart_skill": self.selected_restart_skill,
            "selected_response_function": self.selected_response_function,
            "large_change_signals": list(self.large_change_signals),
            "policy_version": "public_regime_warm_full_selector_v2",
            "reason": self.reason,
        }


@dataclass(frozen=True)
class LandscapeRestartDecision:
    """Sensor-based Warm/Full decision used as a traditional DMOEA control.

    The same retained decisions are evaluated under the public Workbench
    before and after an update.  No optimization rollout, hidden checker,
    reference front, HV, or benchmark/stage identifier enters the decision.
    """

    population_count: int = 0
    sensor_count: int = 0
    evaluated_sensor_count: int = 0
    objective_count: int = 0
    per_objective_displacement: tuple[float, ...] = ()
    normalized_landscape_displacement: float = 0.0
    mean_sensor_displacement: float = 0.0
    old_feasible_count: int = 0
    new_feasible_count: int = 0
    feasibility_flip_rate: float = 0.0
    feasibility_loss_rate: float = 0.0
    objective_dimension_changed: bool = False
    sensor_fraction: float = LANDSCAPE_SENSOR_FRACTION
    displacement_threshold: float = LANDSCAPE_DISPLACEMENT_THRESHOLD
    feasibility_loss_threshold: float = LANDSCAPE_FEASIBILITY_LOSS_THRESHOLD
    selected_restart_skill: str = "warm_restart_v1"
    reason: str = "no landscape displacement above threshold"

    def to_record(self) -> dict[str, Any]:
        return {
            "population_count": int(self.population_count),
            "sensor_count": int(self.sensor_count),
            "evaluated_sensor_count": int(self.evaluated_sensor_count),
            "objective_count": int(self.objective_count),
            "per_objective_displacement": [round(float(value), 6) for value in self.per_objective_displacement],
            "normalized_landscape_displacement": round(float(self.normalized_landscape_displacement), 6),
            "mean_sensor_displacement": round(float(self.mean_sensor_displacement), 6),
            "old_feasible_count": int(self.old_feasible_count),
            "new_feasible_count": int(self.new_feasible_count),
            "feasibility_flip_rate": round(float(self.feasibility_flip_rate), 6),
            "feasibility_loss_rate": round(float(self.feasibility_loss_rate), 6),
            "objective_dimension_changed": bool(self.objective_dimension_changed),
            "sensor_fraction": round(float(self.sensor_fraction), 6),
            "displacement_threshold": round(float(self.displacement_threshold), 6),
            "feasibility_loss_threshold": round(float(self.feasibility_loss_threshold), 6),
            "selected_restart_skill": self.selected_restart_skill,
            "policy_version": "sensor_objective_landscape_warm_full_v1",
            "reason": self.reason,
        }


class LiveOptUpdateLocalizer:
    """Small sub-agent that decides which Workbench slots need patching."""

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)

    def classify(
        self,
        *,
        natural_language_update: str,
        project: ScaffoldProject,
        public_context: dict[str, Any],
        previous_result: EvolutionResult | None = None,
        public_update_history: list[dict[str, Any]] | None = None,
    ) -> tuple[DynamicUpdateImpact, ScaffoldTrace]:
        trace = ScaffoldTrace(model=self.model)
        prompt = build_update_localizer_prompt(
            natural_language_update=natural_language_update,
            project=project,
            public_context=public_context,
            previous_result=previous_result,
            public_update_history=public_update_history,
        )
        trace.prompts.append(prompt)
        started = time.perf_counter()
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": "Classify dynamic optimization updates for a fixed LiveOpt Workbench. Return exactly one JSON object.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=1200,
        )
        trace.latency_seconds = time.perf_counter() - started
        trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(response, dict) else ""
        trace.raw_responses.append(content)
        impact = DynamicUpdateImpact.from_mapping(_extract_json_object(content))
        return impact, trace


class LiveOptWorkbenchPatcher:
    """Patch only setup.py and/or fitness.py for a dynamic update."""

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)

    def patch_slots(
        self,
        *,
        current_slots: dict[str, str],
        natural_language_update: str,
        impact: DynamicUpdateImpact,
        public_context: dict[str, Any],
        previous_error: str = "",
    ) -> tuple[dict[str, str], ScaffoldTrace]:
        trace = ScaffoldTrace(model=self.model)
        if not (impact.patch_setup or impact.patch_fitness):
            return dict(current_slots), trace
        full_regeneration = bool((impact.raw or {}).get("typed_full_regeneration_control"))
        prompt = build_scaffold_patch_prompt(
            current_slots=current_slots,
            natural_language_update=natural_language_update,
            impact=impact,
            public_context=public_context,
            previous_error=previous_error,
        )
        trace.prompts.append(prompt)
        started = time.perf_counter()
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "Regenerate complete standalone Python slots for a fixed LiveOpt Workbench. Return code blocks only."
                        if full_regeneration
                        else "Patch only requested Python code slots for a fixed LiveOpt Workbench. Return code blocks only."
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=5000,
        )
        trace.latency_seconds = time.perf_counter() - started
        trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(response, dict) else ""
        trace.raw_responses.append(content)
        slots = parse_code_slots(content)
        required = []
        if impact.patch_setup:
            required.append("setup.py")
        if impact.patch_fitness:
            required.append("fitness.py")
        missing = [name for name in required if name not in slots]
        if missing:
            raise ValueError("missing requested patch slots: " + ", ".join(missing))
        return merge_code_slots(current_slots, content), trace


class LiveOptDataPatcher:
    """Patch public_context data from natural language without touching code."""

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)

    def patch_context(
        self,
        *,
        public_context: dict[str, Any],
        natural_language_update: str,
        project: ScaffoldProject,
        max_patch_repairs: int = 0,
        public_update_history: list[dict[str, Any]] | None = None,
    ) -> tuple[dict[str, Any], ScaffoldTrace, dict[str, Any]]:
        trace = ScaffoldTrace(model=self.model)
        previous_error = ""
        last_patch: dict[str, Any] = {}
        for attempt in range(max(1, int(max_patch_repairs) + 1)):
            prompt = build_data_patch_prompt(
                public_context=public_context,
                natural_language_update=natural_language_update,
                project=project,
                previous_error=previous_error,
                previous_patch=last_patch,
                public_update_history=public_update_history,
            )
            trace.prompts.append(prompt)
            started = time.perf_counter()
            response = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": "Patch public optimization data from a natural-language update. Return exactly one JSON object.",
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=2200,
            )
            trace.latency_seconds += time.perf_counter() - started
            trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(response, dict) else ""
            trace.raw_responses.append(content)
            try:
                patch = _extract_json_object(content)
                last_patch = patch
                patched = apply_public_context_patch(public_context, patch)
                return patched, trace, patch
            except Exception as exc:  # noqa: BLE001
                if is_llm_quota_limit_error(exc):
                    raise
                previous_error = f"{type(exc).__name__}: {exc}"
                trace.errors.append(previous_error)
                if attempt >= max_patch_repairs:
                    raise ValueError("data patch repair failed: " + previous_error) from exc
        raise ValueError("data patch repair failed without producing a patch")


class ScaffoldRestartSeedBuilder:
    """Convert scaffold archive/population memory into generic genome seeds."""

    def build(
        self,
        *,
        restart_skill: str,
        previous_result: EvolutionResult | None,
        segments: list[SegmentSpec],
        population_size: int,
        seed: int | None = None,
        evaluate: Callable[[dict[str, Any], dict[str, Any]], Any] | None = None,
        data: dict[str, Any] | None = None,
        objective_shift: ObjectiveSpaceShift | None = None,
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        if restart_skill not in RESTART_SKILLS:
            raise ValueError(f"unsupported restart_skill: {restart_skill}")
        shift = objective_shift
        if restart_skill == "full_restart_v1" or previous_result is None:
            return [], {
                "restart_skill": restart_skill,
                "source": "fresh_current_encoding",
                "seed_count": 0,
                "fresh_population_ratio": 1.0,
                "history_population_ratio": 0.0,
            }
        rng = random.Random(seed)
        candidates = candidate_genomes(previous_result)
        if not candidates:
            return [], {"restart_skill": restart_skill, "source": "empty_previous_memory", "seed_count": 0}
        migration_metadata: dict[str, Any] = {}
        if restart_skill in {"adaptive_mix_v1", "warm_restart_v1"}:
            if restart_skill == "adaptive_mix_v1":
                if shift is None:
                    raise ValueError("adaptive_mix_v1 requires an objective_space_shift record")
                fresh_ratio = float(shift.fresh_population_ratio)
                fresh_ratio = max(0.0, min(1.0, fresh_ratio))
                history_seed_target = max(0, min(population_size, int(round(population_size * (1.0 - fresh_ratio)))))
            else:
                fresh_ratio = 0.5
                history_seed_target = self._warm_history_seed_target(population_size)
            seeds = self._greedy_repair_seeds(
                candidates,
                segments,
                population_size,
                rng,
                evaluate,
                data or {},
                history_seed_target=history_seed_target,
            )
            source = (
                "objective_space_adaptive_population_mix"
                if restart_skill == "adaptive_mix_v1"
                else "greedy_repair_from_previous_population"
            )
            migration_metadata = {
                "warm_history_seed_target": history_seed_target,
                "warm_history_seed_ratio": history_seed_target / max(1, int(population_size)),
                "history_population_ratio": history_seed_target / max(1, int(population_size)),
                "fresh_population_ratio": 1.0 - history_seed_target / max(1, int(population_size)),
                "warm_ratio_policy": (
                    "objective_space_population_mix_v1"
                    if restart_skill == "adaptive_mix_v1"
                    else "fixed_half_population"
                ),
                "implicit_fresh_seed_slots": max(0, int(population_size) - len(seeds)),
            }
        elif restart_skill == "population_transfer_v1":
            seeds, migration_metadata = self._population_transfer(
                candidates,
                segments,
                population_size,
                rng,
                evaluate,
                data or {},
            )
            source = "direct_population_migration"
        else:  # pragma: no cover - guarded by validation above.
            seeds = []
            source = "unknown"
        seeds = unique_genomes(seeds, population_size)
        feasible_seed_count = len(filter_feasible_seeds(seeds, evaluate, data or {}))
        metadata = {
            "restart_skill": restart_skill,
            "source": source,
            "seed_count": len(seeds),
            "feasible_seed_count": feasible_seed_count,
            "previous_candidate_count": len(candidates),
            "realized_history_population_ratio": len(seeds) / max(1, int(population_size)),
            "realized_fresh_population_ratio": 1.0 - len(seeds) / max(1, int(population_size)),
        }
        if migration_metadata:
            metadata.update(migration_metadata)
            metadata.setdefault("implicit_fresh_seed_slots", max(0, int(population_size) - len(seeds)))
        return seeds, metadata

    def _warm_seeds(
        self,
        candidates: list[Candidate],
        segments: list[SegmentSpec],
        population_size: int,
        rng: random.Random,
        *,
        history_seed_target: int | None = None,
    ) -> list[dict[str, Any]]:
        base = coerce_genome(candidates[0].genome, segments)
        target = (
            max(1, min(population_size, population_size // 2))
            if history_seed_target is None
            else int(history_seed_target)
        )
        if target <= 0:
            return []
        target = max(1, min(population_size, int(target)))
        seeds = [base]
        while len(seeds) < target:
            seeds.append(mutate_genome(base, segments, rng))
        return seeds

    def _warm_history_seed_target(self, population_size: int) -> int:
        return max(1, min(population_size, population_size // 2))

    def _population_transfer(
        self,
        candidates: list[Candidate],
        segments: list[SegmentSpec],
        population_size: int,
        rng: random.Random,
        evaluate: Callable[[dict[str, Any], dict[str, Any]], Any] | None,
        data: dict[str, Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        """Directly migrate the previous typed population/archive.

        Repair belongs to ``warm_restart_v1``. Keeping transfer as a direct
        operator makes the restart skills separable and auditable: the public
        probe chooses between direct migration, greedy repair, and full restart.
        """

        del rng
        probe_limit = max(1, min(len(candidates), population_size))
        direct_evaluated: list[Candidate] = []
        seeds: list[dict[str, Any]] = []

        for candidate in candidates[:probe_limit]:
            direct_genome = coerce_genome(candidate.genome, segments)
            seeds.append(direct_genome)
            direct_result = _safe_evaluate_raw(evaluate, direct_genome, data)
            if direct_result is not None:
                direct_evaluated.append(Candidate(direct_genome, direct_result))

        feasible_direct = [candidate for candidate in direct_evaluated if candidate.result and candidate.result.feasible]
        metadata = {
            "migration_operator": "direct_population_migration",
            "direct_evaluated_count": len(direct_evaluated),
            "direct_feasible_count": len(feasible_direct),
            "repaired_feasible_count": 0,
            "boundary_seed_count": 0,
            "retained_direct_count": len(unique_genomes(seeds, population_size)),
            "retained_repaired_count": 0,
            "local_variant_count": 0,
            "transfer_target": population_size,
            "evaluated_candidate_count": probe_limit,
            "history_population_ratio": 1.0,
            "fresh_population_ratio": 0.0,
        }
        return seeds, metadata

    def _greedy_repair_seeds(
        self,
        candidates: list[Candidate],
        segments: list[SegmentSpec],
        population_size: int,
        rng: random.Random,
        evaluate: Callable[[dict[str, Any], dict[str, Any]], Any] | None,
        data: dict[str, Any],
        *,
        history_seed_target: int | None = None,
    ) -> list[dict[str, Any]]:
        target = (
            max(1, min(population_size, population_size // 2))
            if history_seed_target is None
            else int(history_seed_target)
        )
        if target <= 0:
            return []
        target = max(1, min(population_size, int(target)))
        seeds = []
        candidate_pool = _restart_seed_candidates(candidates, max(target, min(len(candidates), population_size)))
        for candidate in candidate_pool:
            migrated = coerce_genome(candidate.genome, segments)
            repaired, _ = greedy_repair_genome(migrated, segments, evaluate, data, rng)
            seeds.append(repaired)
            if len(seeds) >= target:
                break
        while seeds and len(seeds) < target:
            repaired, _ = greedy_repair_genome(mutate_genome(seeds[-1], segments, rng), segments, evaluate, data, rng)
            seeds.append(repaired)
        return seeds or self._warm_seeds(
            candidates,
            segments,
            population_size,
            rng,
            history_seed_target=target,
        )

def calibrate_restart_skill_from_public_evidence(
    *,
    restart_skill: str,
    objective_shift: ObjectiveSpaceShift | None = None,
    natural_language_update: str = "",
    project: ScaffoldProject | None = None,
    data_patch: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Choose fixed warm or full restart from public regime evidence."""

    if restart_skill not in RESTART_SKILLS:
        raise ValueError(f"unsupported restart_skill: {restart_skill}")
    if objective_shift is None:
        return restart_skill, ""
    if objective_shift.sample_count <= 0:
        return "full_restart_v1", objective_shift.reason
    return objective_shift.selected_restart_skill, objective_shift.reason


def select_dynamic_restart_from_semantic_evidence(
    *,
    impact: DynamicUpdateImpact,
    semantic_decision: SemanticRestartDecision | None = None,
) -> DynamicUpdateImpact:
    restart_skill, reason = select_restart_skill_from_semantic_evidence(
        semantic_decision=semantic_decision,
    )
    updated = impact
    if restart_skill != impact.restart_skill:
        updated = impact.with_restart_skill(
            restart_skill,
            reason=("public regime Warm/Full rule: " + reason),
        )
    raw = dict(updated.raw)
    if semantic_decision is not None:
        raw["semantic_restart_gate"] = semantic_decision.to_record()
    raw["restart_selection"] = {
        "rule": "verified_semantic_full_else_fixed_warm",
        "semantic_full_vote": bool(semantic_decision and semantic_decision.verified_full_vote),
        "selected_restart_skill": restart_skill,
        "reason": reason,
    }
    return replace(updated, raw=raw)


def select_restart_skill_from_semantic_evidence(
    *,
    semantic_decision: SemanticRestartDecision | None = None,
    semantic_full_vote: bool | None = None,
) -> tuple[str, str]:
    """Choose Full only from a verified semantic vote; otherwise use Fixed Warm."""

    semantic_full = (
        bool(semantic_decision and semantic_decision.verified_full_vote)
        if semantic_full_vote is None
        else bool(semantic_full_vote)
    )
    selected = "full_restart_v1" if semantic_full else "warm_restart_v1"
    semantic_reason = semantic_decision.reason if semantic_decision is not None else "semantic gate not used"
    return selected, (
        f"semantic-only selection: verified Full={semantic_full} ({semantic_reason}); "
        f"selected={selected}"
    )


def select_restart_skill_from_landscape_change(
    *,
    previous_project: ScaffoldProject,
    project: ScaffoldProject,
    previous_result: EvolutionResult | None,
    seed: int = 0,
    stage_index: int = 0,
    sensor_fraction: float = LANDSCAPE_SENSOR_FRACTION,
    displacement_threshold: float = LANDSCAPE_DISPLACEMENT_THRESHOLD,
    feasibility_loss_threshold: float = LANDSCAPE_FEASIBILITY_LOSS_THRESHOLD,
) -> LandscapeRestartDecision:
    """Choose Warm or Full from sensor re-evaluations in objective space.

    This is an executable traditional-DMOEA comparison, not LiveOpt's active
    selector.  A deterministic random 10% of the incoming population is
    evaluated under the old and new public objective functions.  For each
    objective, severity is the mean absolute change divided by the larger old
    or new magnitude for the same sensor; the maximum objective severity is
    used so a severe change is not averaged away by unchanged objectives.
    Full is selected when that bounded relative severity reaches 0.5, the
    objective dimension changes, or at least half of previously feasible
    sensors become infeasible.  Otherwise the policy uses the same Fixed-Warm
    action as the matched control.
    """

    if not 0.0 < sensor_fraction <= 1.0:
        raise ValueError("sensor_fraction must be in (0, 1]")
    if displacement_threshold <= 0.0:
        raise ValueError("displacement_threshold must be positive")
    if not 0.0 <= feasibility_loss_threshold <= 1.0:
        raise ValueError("feasibility_loss_threshold must be in [0, 1]")

    if previous_result is None:
        return LandscapeRestartDecision(
            sensor_fraction=sensor_fraction,
            displacement_threshold=displacement_threshold,
            feasibility_loss_threshold=feasibility_loss_threshold,
            selected_restart_skill="full_restart_v1",
            reason="no incoming population is available for landscape sensors; select full",
        )

    source_population = list(previous_result.population or previous_result.archive or [])
    population = [candidate for candidate in source_population if isinstance(candidate.genome, dict)]
    population_count = len(population)
    if not population:
        return LandscapeRestartDecision(
            population_count=0,
            sensor_fraction=sensor_fraction,
            displacement_threshold=displacement_threshold,
            feasibility_loss_threshold=feasibility_loss_threshold,
            selected_restart_skill="full_restart_v1",
            reason="incoming population contains no executable genomes; select full",
        )

    sensor_count = min(
        population_count,
        max(LANDSCAPE_MIN_SENSORS, int(math.ceil(population_count * sensor_fraction))),
    )
    rng = random.Random(int(seed) * 1_000_003 + int(stage_index) * 9_176 + 2_029)
    sensor_indices = sorted(rng.sample(range(population_count), sensor_count))

    objective_pairs: list[tuple[list[float], list[float]]] = []
    old_feasible_count = 0
    new_feasible_count = 0
    feasibility_flips = 0
    feasibility_losses = 0
    objective_dimension_changed = False
    for index in sensor_indices:
        candidate = population[index]
        genome = copy.deepcopy(candidate.genome)
        old_result = _safe_evaluate(previous_project, genome) or candidate.result
        new_result = _safe_evaluate(project, genome)
        if old_result is None or new_result is None:
            continue
        old_feasible = bool(old_result.feasible)
        new_feasible = bool(new_result.feasible)
        old_feasible_count += int(old_feasible)
        new_feasible_count += int(new_feasible)
        feasibility_flips += int(old_feasible != new_feasible)
        feasibility_losses += int(old_feasible and not new_feasible)
        old_vector = _public_objective_vector(old_result)
        new_vector = _public_objective_vector(new_result)
        if len(old_vector) != len(new_vector):
            objective_dimension_changed = True
            continue
        if old_vector and all(math.isfinite(value) for value in old_vector + new_vector):
            objective_pairs.append((old_vector, new_vector))

    evaluated_sensor_count = len(objective_pairs)
    objective_count = min((len(old) for old, _ in objective_pairs), default=0)
    per_objective_displacement: list[float] = []
    for objective_index in range(objective_count):
        displacements = [
            abs(new[objective_index] - old[objective_index])
            / max(abs(old[objective_index]), abs(new[objective_index]), 1e-12)
            for old, new in objective_pairs
        ]
        per_objective_displacement.append(sum(displacements) / max(1, len(displacements)))

    sensor_displacements: list[float] = []
    if objective_count:
        for old, new in objective_pairs:
            squared = sum(
                (
                    (new[index] - old[index])
                    / max(abs(old[index]), abs(new[index]), 1e-12)
                )
                ** 2
                for index in range(objective_count)
            )
            sensor_displacements.append(math.sqrt(squared / objective_count))
    normalized_displacement = max(per_objective_displacement, default=0.0)
    mean_sensor_displacement = (
        sum(sensor_displacements) / len(sensor_displacements) if sensor_displacements else 0.0
    )
    feasibility_flip_rate = feasibility_flips / max(1, sensor_count)
    feasibility_loss_rate = feasibility_losses / max(1, old_feasible_count)

    full_signals: list[str] = []
    if evaluated_sensor_count == 0:
        full_signals.append("no valid paired sensor evaluation")
    if objective_dimension_changed:
        full_signals.append("objective dimension changed")
    if normalized_displacement >= displacement_threshold:
        full_signals.append(
            f"relative objective change {normalized_displacement:.3f} >= {displacement_threshold:.3f}"
        )
    if old_feasible_count and feasibility_loss_rate >= feasibility_loss_threshold:
        full_signals.append(
            f"feasibility loss {feasibility_loss_rate:.3f} >= {feasibility_loss_threshold:.3f}"
        )
    selected = "full_restart_v1" if full_signals else "warm_restart_v1"
    reason = (
        "sensor objective-landscape gate selects full: " + "; ".join(full_signals)
        if full_signals
        else (
            "sensor objective-landscape gate selects fixed warm: "
            f"displacement={normalized_displacement:.3f}, feasibility loss={feasibility_loss_rate:.3f}"
        )
    )
    return LandscapeRestartDecision(
        population_count=population_count,
        sensor_count=sensor_count,
        evaluated_sensor_count=evaluated_sensor_count,
        objective_count=objective_count,
        per_objective_displacement=tuple(per_objective_displacement),
        normalized_landscape_displacement=normalized_displacement,
        mean_sensor_displacement=mean_sensor_displacement,
        old_feasible_count=old_feasible_count,
        new_feasible_count=new_feasible_count,
        feasibility_flip_rate=feasibility_flip_rate,
        feasibility_loss_rate=feasibility_loss_rate,
        objective_dimension_changed=objective_dimension_changed,
        sensor_fraction=sensor_fraction,
        displacement_threshold=displacement_threshold,
        feasibility_loss_threshold=feasibility_loss_threshold,
        selected_restart_skill=selected,
        reason=reason,
    )


def estimate_objective_space_shift(
    *,
    previous_project: ScaffoldProject,
    project: ScaffoldProject,
    previous_result: EvolutionResult | None,
    population_size: int,
    seed: int | None = None,
) -> ObjectiveSpaceShift:
    """Select warm or full restart without trial optimization.

    Retained candidates are evaluated once under the old and patched public
    Workbenches. Compiled public-state churn, decision-support replacement, and
    objective-dimension change identify a new regime. Distribution location,
    scale, direct feasibility, and rank reversal are recorded for diagnosis but
    cannot alone force a restart. No rollout, hidden evaluator, reference set,
    or HV/IGD signal is used by this policy.
    """

    del seed
    candidates = candidate_genomes(previous_result) if previous_result is not None else []
    if not candidates:
        return ObjectiveSpaceShift(
            selected_restart_skill="full_restart_v1",
            selected_response_function="full_restart",
            fresh_population_ratio=1.0,
            history_population_ratio=0.0,
            reason="no previous public population/archive to compare",
        )
    sample_limit = max(8, min(len(candidates), max(population_size, 24)))
    sampled = candidates[:sample_limit]
    old_scalars: list[float] = []
    new_scalars: list[float] = []
    shifts: list[float] = []
    objective_pairs: list[tuple[list[float], list[float]]] = []
    direct_feasible = 0
    objective_dim_changed = False
    current_objective_count = 0
    for candidate in sampled:
        old_result = candidate.result or _safe_evaluate(previous_project, candidate.genome)
        direct_genome = coerce_genome(candidate.genome, project.segments)
        direct_result = _safe_evaluate(project, direct_genome)
        if direct_result and direct_result.feasible:
            direct_feasible += 1
        if old_result and direct_result:
            old_scalar = float(old_result.scalar)
            new_scalar = float(direct_result.scalar)
            if math.isfinite(old_scalar) and math.isfinite(new_scalar):
                old_scalars.append(old_scalar)
                new_scalars.append(new_scalar)
                shifts.append(abs(new_scalar - old_scalar) / max(abs(old_scalar), 1.0))
            old_vector = _public_objective_vector(old_result)
            new_vector = _public_objective_vector(direct_result)
            old_dim = len(old_vector)
            new_dim = len(new_vector)
            current_objective_count = max(current_objective_count, new_dim)
            if old_dim != new_dim:
                objective_dim_changed = True
            elif old_dim and all(math.isfinite(value) for value in old_vector + new_vector):
                objective_pairs.append((old_vector, new_vector))
    sample_count = len(sampled)
    rank_correlation = _spearman_rank_correlation(old_scalars, new_scalars)
    center_shift, scale_shift = _objective_distribution_change(objective_pairs)
    rank_disruption = 0.0 if rank_correlation is None else _clip01((1.0 - rank_correlation) / 2.0)
    direct_feasible_ratio = direct_feasible / max(1, sample_count)
    segment_distance = _segment_distance(previous_project.segments, project.segments)
    state_churn, changed_fact_count, union_fact_count = _public_state_churn(
        previous_project.data,
        project.data,
    )
    large_change_signals: list[str] = []
    if state_churn >= REGIME_DATA_CHURN_THRESHOLD and changed_fact_count >= REGIME_DATA_CHANGED_FACTS_MIN:
        large_change_signals.append("public_state_replacement")
    if segment_distance >= REGIME_SEGMENT_DISTANCE_THRESHOLD:
        large_change_signals.append("typed_decision_support_replacement")
    if objective_dim_changed:
        large_change_signals.append("objective_dimension_change")
    if large_change_signals and rank_disruption >= REGIME_RANK_DISRUPTION_THRESHOLD:
        large_change_signals.append("corroborating_rank_reversal")

    regime_score = max(
        _clip01(state_churn / REGIME_DATA_CHURN_THRESHOLD)
        if changed_fact_count >= REGIME_DATA_CHANGED_FACTS_MIN
        else 0.0,
        _clip01(segment_distance / REGIME_SEGMENT_DISTANCE_THRESHOLD),
        1.0 if objective_dim_changed else 0.0,
    )
    full_restart = bool(large_change_signals)
    selected_restart_skill = "full_restart_v1" if full_restart else "warm_restart_v1"
    fresh_population_ratio = 1.0 if full_restart else 0.5
    history_population_ratio = 1.0 - fresh_population_ratio
    decision = "full" if full_restart else "fixed warm"
    signal_text = ", ".join(large_change_signals) if large_change_signals else "no regime-replacement signal"
    reason = (
        f"public regime score={regime_score:.3f}, state churn={state_churn:.3f} "
        f"({changed_fact_count}/{union_fact_count} changed facts), segment distance={segment_distance:.3f}, "
        f"rank disruption={rank_disruption:.3f}; select {decision}: {signal_text}"
    )
    return ObjectiveSpaceShift(
        sample_count=sample_count,
        segment_distance=segment_distance,
        direct_feasible_ratio=direct_feasible_ratio,
        current_objective_count=current_objective_count,
        rank_correlation=rank_correlation,
        median_relative_scalar_shift=_median(shifts),
        objective_dimension_changed=objective_dim_changed,
        objective_center_shift=center_shift,
        objective_scale_shift=scale_shift,
        objective_rank_disruption=rank_disruption,
        public_state_churn=state_churn,
        public_state_changed_fact_count=changed_fact_count,
        public_state_union_fact_count=union_fact_count,
        objective_space_shift=regime_score,
        fresh_population_ratio=fresh_population_ratio,
        history_population_ratio=history_population_ratio,
        selected_restart_skill=selected_restart_skill,
        selected_response_function="public_regime_warm_full_selector",
        large_change_signals=tuple(large_change_signals),
        reason=reason,
    )


def _public_state_churn(old_data: dict[str, Any], new_data: dict[str, Any]) -> tuple[float, int, int]:
    """Return Jaccard churn over stable, public, compiled-state facts."""

    old_facts = _stable_public_facts(old_data)
    new_facts = _stable_public_facts(new_data)
    union = old_facts | new_facts
    changed = old_facts ^ new_facts
    return len(changed) / max(1, len(union)), len(changed), len(union)


def _stable_public_facts(value: Any, path: tuple[str, ...] = ()) -> set[tuple[str, str]]:
    facts: set[tuple[str, str]] = set()
    if isinstance(value, dict):
        for key in sorted(value, key=str):
            facts.update(_stable_public_facts(value[key], path + (str(key),)))
        return facts
    if isinstance(value, list):
        identity_key = _stable_row_identity_key(value)
        for index, item in enumerate(value):
            token = str(index)
            if identity_key is not None and isinstance(item, dict):
                token = f"{identity_key}={item.get(identity_key)}"
            facts.update(_stable_public_facts(item, path + (token,)))
        return facts
    facts.add(("/".join(path), json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)))
    return facts


def _stable_row_identity_key(values: list[Any]) -> str | None:
    if not values or not all(isinstance(value, dict) for value in values):
        return None
    common = set(values[0])
    for value in values[1:]:
        common.intersection_update(value)
    preferred = sorted(
        common,
        key=lambda key: (
            0 if key == "id" else 1 if key.endswith("_id") else 2 if key.endswith("_code") else 3,
            key,
        ),
    )
    for key in preferred:
        if not (key == "id" or key.endswith("_id") or key.endswith("_code")):
            continue
        identities = [json.dumps(value.get(key), ensure_ascii=False, sort_keys=True, default=str) for value in values]
        if len(set(identities)) == len(identities):
            return key
    return None


def _public_objective_vector(result: Any) -> list[float]:
    objectives = list(result.objectives or [])
    return [float(value) for value in objectives] if objectives else [float(result.scalar)]


def _objective_distribution_change(
    pairs: list[tuple[list[float], list[float]]],
) -> tuple[float, float]:
    if not pairs:
        return 0.0, 0.0
    dimension = min(len(old) for old, _ in pairs)
    center_components: list[float] = []
    scale_components: list[float] = []
    for objective_idx in range(dimension):
        old_values = sorted(old[objective_idx] for old, _ in pairs)
        new_values = sorted(new[objective_idx] for _, new in pairs)
        old_center = float(_median(old_values) or 0.0)
        new_center = float(_median(new_values) or 0.0)
        old_scale = _quantile(old_values, 0.90) - _quantile(old_values, 0.10)
        new_scale = _quantile(new_values, 0.90) - _quantile(new_values, 0.10)
        denominator = max(abs(old_center), abs(old_scale), 1.0)
        epsilon = max(abs(old_center), 1.0) * 1e-6
        center_components.append(abs(new_center - old_center) / denominator)
        scale_components.append(abs(math.log((abs(new_scale) + epsilon) / (abs(old_scale) + epsilon))))
    return float(_median(center_components) or 0.0), float(_median(scale_components) or 0.0)


def _quantile(values: list[float], probability: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    position = max(0.0, min(1.0, probability)) * (len(values) - 1)
    lower = int(math.floor(position))
    upper = int(math.ceil(position))
    if lower == upper:
        return float(values[lower])
    weight = position - lower
    return float(values[lower]) * (1.0 - weight) + float(values[upper]) * weight


def _clip01(value: float) -> float:
    return max(0.0, min(1.0, float(value)))


def greedy_repair_genome(
    genome: dict[str, Any],
    segments: list[SegmentSpec],
    evaluate: Callable[[dict[str, Any], dict[str, Any]], Any] | None,
    data: dict[str, Any],
    rng: random.Random,
    *,
    max_moves: int = 80,
) -> tuple[dict[str, Any], Any | None]:
    best = coerce_genome(genome, segments)
    best_result = _safe_evaluate_raw(evaluate, best, data)
    if evaluate is None:
        return best, best_result
    moves = 0
    improved = True
    while improved and moves < max_moves:
        improved = False
        for segment in segments:
            for proposal_value in _local_segment_proposals(best.get(segment.name), segment, rng):
                trial = copy.deepcopy(best)
                trial[segment.name] = proposal_value
                trial = coerce_genome(trial, segments)
                result = _safe_evaluate_raw(evaluate, trial, data)
                moves += 1
                if result and (best_result is None or _fitness_better(result, best_result)):
                    best = trial
                    best_result = result
                    improved = True
                    break
                if moves >= max_moves:
                    break
            if improved or moves >= max_moves:
                break
    return best, best_result


def _local_segment_proposals(value: Any, segment: SegmentSpec, rng: random.Random) -> list[Any]:
    proposals: list[Any] = []
    if segment.kind in {"assignment", "optional_assignment"}:
        current = dict(value) if isinstance(value, dict) else {}
        options = list(segment.resources)
        if segment.kind == "optional_assignment" or segment.allow_none:
            options.append(None)
        demands = list(segment.demands)
        rng.shuffle(demands)
        for demand in demands[: min(len(demands), 24)]:
            for resource in options[: min(len(options), 16)]:
                if current.get(demand) == resource:
                    continue
                candidate = dict(current)
                candidate[demand] = copy.deepcopy(resource)
                proposals.append(candidate)
        return proposals
    if segment.kind == "binary_vector":
        items = list(value) if isinstance(value, list) else [0] * segment.length
        for idx in range(min(segment.length, 64)):
            candidate = list(items)
            candidate[idx] = 1 - int(candidate[idx]) if idx < len(candidate) else 1
            proposals.append(candidate[: segment.length])
        return proposals
    if segment.kind == "int_vector":
        items = list(value) if isinstance(value, list) else []
        for idx in range(min(segment.length, 32)):
            base = int(items[idx]) if idx < len(items) else int(round(_mid(segment, idx)))
            for delta in (-1, 1):
                candidate = list(items)[: segment.length]
                while len(candidate) < segment.length:
                    candidate.append(int(round(_mid(segment, len(candidate)))))
                candidate[idx] = int(round(_clip(base + delta, _bound(segment.lower, idx), _bound(segment.upper, idx))))
                proposals.append(candidate)
        return proposals
    if segment.kind == "real_vector":
        items = list(value) if isinstance(value, list) else []
        for idx in range(min(segment.length, 16)):
            lo = _bound(segment.lower, idx)
            hi = _bound(segment.upper, idx)
            base = float(items[idx]) if idx < len(items) else _mid(segment, idx)
            step = max((hi - lo) * 0.05, 1e-9)
            for candidate_value in (base - step, base + step, _mid(segment, idx)):
                candidate = list(items)[: segment.length]
                while len(candidate) < segment.length:
                    candidate.append(_mid(segment, len(candidate)))
                candidate[idx] = _clip(candidate_value, lo, hi)
                proposals.append(candidate)
        return proposals
    if segment.kind == "choice_vector":
        items = list(value) if isinstance(value, list) else []
        for idx in range(min(segment.length, 24)):
            for option in list(segment.options)[:16]:
                candidate = list(items)[: segment.length]
                while len(candidate) < segment.length:
                    candidate.append(copy.deepcopy(segment.options[0]))
                if candidate[idx] == option:
                    continue
                candidate[idx] = copy.deepcopy(option)
                proposals.append(candidate)
        return proposals
    if segment.kind == "permutation":
        items = list(value) if isinstance(value, list) else list(segment.values)
        for idx in range(min(max(0, len(items) - 1), 32)):
            candidate = list(items)
            candidate[idx], candidate[idx + 1] = candidate[idx + 1], candidate[idx]
            proposals.append(candidate)
        return proposals
    return proposals


def _safe_evaluate(project: ScaffoldProject, genome: dict[str, Any]) -> Any | None:
    return _safe_evaluate_raw(project.evaluate, genome, project.data)


def _safe_evaluate_raw(
    evaluate: Callable[[dict[str, Any], dict[str, Any]], Any] | None,
    genome: dict[str, Any],
    data: dict[str, Any],
) -> Any | None:
    if evaluate is None:
        return None
    try:
        return coerce_fitness_result(evaluate(genome, data), genome)
    except Exception:
        return None


def _fitness_better(candidate: Any, incumbent: Any) -> bool:
    if candidate is None:
        return False
    if incumbent is None:
        return True
    candidate_key = (0 if candidate.feasible else 1, float(candidate.scalar))
    incumbent_key = (0 if incumbent.feasible else 1, float(incumbent.scalar))
    return candidate_key < incumbent_key


def _select_transfer_candidates(candidates: list[Candidate], limit: int) -> list[Candidate]:
    if limit <= 0 or not candidates:
        return []
    feasible = [candidate for candidate in candidates if candidate.result and candidate.result.feasible]
    pool = feasible or [candidate for candidate in candidates if candidate.result is not None]
    if not pool:
        return []
    multi = any(len(candidate.result.objectives or []) > 1 for candidate in pool if candidate.result)
    if multi:
        return nsga2_select(list(pool), min(limit, len(pool)))
    return sorted(pool, key=lambda candidate: (0 if candidate.result and candidate.result.feasible else 1, float(candidate.result.scalar if candidate.result else float("inf"))))[
        :limit
    ]


def _restart_seed_candidates(candidates: list[Candidate], limit: int) -> list[Candidate]:
    """Order reusable memory for restart seeding without problem-specific rules."""

    if limit <= 0:
        return []
    feasible = [candidate for candidate in candidates if candidate.result and candidate.result.feasible]
    pool = feasible or [candidate for candidate in candidates if candidate.result is not None]
    if not pool:
        return candidates[:limit]
    multi = any(len(candidate.result.objectives or []) > 1 for candidate in pool if candidate.result)
    if not multi:
        return _select_transfer_candidates(pool, limit)

    selected: list[Candidate] = []
    selected.extend(_objective_extreme_candidates(pool))
    selected.extend(_objective_knee_candidates(pool))
    remaining = max(limit, min(len(pool), limit * 2))
    selected.extend(nsga2_select(list(pool), min(remaining, len(pool))))
    return unique_candidate_genomes(selected, limit)


def _objective_extreme_candidates(candidates: list[Candidate]) -> list[Candidate]:
    feasible = [candidate for candidate in candidates if candidate.result and candidate.result.feasible and candidate.result.objectives]
    if not feasible:
        return []
    dim = min((len(candidate.result.objectives) for candidate in feasible if candidate.result), default=0)
    if dim <= 1:
        return _select_transfer_candidates(feasible, min(2, len(feasible)))
    extremes: list[Candidate] = []
    for objective_idx in range(dim):
        best = min(feasible, key=lambda candidate: float(candidate.result.objectives[objective_idx] if candidate.result else float("inf")))
        extremes.append(best)
    return unique_candidate_genomes(extremes, len(extremes))


def _objective_knee_candidates(candidates: list[Candidate], limit: int = 4) -> list[Candidate]:
    feasible = [candidate for candidate in candidates if candidate.result and candidate.result.feasible and candidate.result.objectives]
    if not feasible or limit <= 0:
        return []
    dim = min((len(candidate.result.objectives) for candidate in feasible if candidate.result), default=0)
    if dim <= 1:
        return []
    lows = [min(float(candidate.result.objectives[idx]) for candidate in feasible if candidate.result) for idx in range(dim)]
    highs = [max(float(candidate.result.objectives[idx]) for candidate in feasible if candidate.result) for idx in range(dim)]
    scored: list[tuple[float, float, Candidate]] = []
    for candidate in feasible:
        assert candidate.result is not None
        normalized = []
        for idx in range(dim):
            value = float(candidate.result.objectives[idx])
            span = max(highs[idx] - lows[idx], 1e-9)
            normalized.append((value - lows[idx]) / span)
        sum_score = sum(normalized)
        balance = sum(abs(value - 0.5) for value in normalized)
        scored.append((sum_score, balance, candidate))
    best_sum = sorted(scored, key=lambda item: (item[0], item[1]))
    balanced = sorted(scored, key=lambda item: (item[1], item[0]))
    return unique_candidate_genomes([item[2] for item in best_sum[:limit] + balanced[:limit]], limit)


def _spearman_rank_correlation(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    rank_x = _ranks(xs)
    rank_y = _ranks(ys)
    mean_x = sum(rank_x) / len(rank_x)
    mean_y = sum(rank_y) / len(rank_y)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(rank_x, rank_y))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in rank_x))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in rank_y))
    if den_x <= 0.0 or den_y <= 0.0:
        return None
    return num / (den_x * den_y)


def _ranks(values: list[float]) -> list[float]:
    indexed = sorted(enumerate(values), key=lambda item: item[1])
    ranks = [0.0] * len(values)
    idx = 0
    while idx < len(indexed):
        end = idx + 1
        while end < len(indexed) and indexed[end][1] == indexed[idx][1]:
            end += 1
        avg_rank = (idx + end - 1) / 2.0
        for pos in range(idx, end):
            ranks[indexed[pos][0]] = avg_rank
        idx = end
    return ranks


def _median(values: list[float]) -> float | None:
    finite = sorted(value for value in values if math.isfinite(value))
    if not finite:
        return None
    mid = len(finite) // 2
    if len(finite) % 2:
        return finite[mid]
    return 0.5 * (finite[mid - 1] + finite[mid])


def _segment_distance(old_segments: list[SegmentSpec], new_segments: list[SegmentSpec]) -> float:
    old = [_segment_signature(segment) for segment in old_segments]
    new = [_segment_signature(segment) for segment in new_segments]
    if not old and not new:
        return 0.0
    if len(old) != len(new):
        return 1.0
    distances = [_single_segment_distance(a, b) for a, b in zip(old, new)]
    return sum(distances) / max(1, len(distances))


def _segment_signature(segment: SegmentSpec) -> dict[str, Any]:
    return {
        "name": segment.name,
        "kind": segment.kind,
        "length": segment.length,
        "values": list(segment.values),
        "options": list(segment.options),
        "demands": list(segment.demands),
        "resources": list(segment.resources),
        "allow_none": bool(segment.allow_none),
    }


def _single_segment_distance(old: dict[str, Any], new: dict[str, Any]) -> float:
    if old["kind"] != new["kind"] or old["name"] != new["name"]:
        return 1.0
    penalties = []
    for key in ("values", "options", "demands", "resources"):
        penalties.append(1.0 - _jaccard(old.get(key, []), new.get(key, [])))
    if old.get("length") or new.get("length"):
        penalties.append(abs(float(old.get("length") or 0) - float(new.get("length") or 0)) / max(float(old.get("length") or 0), float(new.get("length") or 0), 1.0))
    if old.get("allow_none") != new.get("allow_none"):
        penalties.append(0.25)
    return min(1.0, sum(penalties) / max(1, len(penalties)))


def _jaccard(left: list[Any], right: list[Any]) -> float:
    left_set = {json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) for value in left}
    right_set = {json.dumps(value, ensure_ascii=False, sort_keys=True, default=str) for value in right}
    if not left_set and not right_set:
        return 1.0
    return len(left_set & right_set) / max(1, len(left_set | right_set))


class LiveOptDynamicRunner:
    """Maintain one scaffold project across natural-language updates."""

    def __init__(
        self,
        project: ScaffoldProject,
        *,
        public_context: dict[str, Any] | None = None,
        result: EvolutionResult | None = None,
        localizer: LiveOptUpdateLocalizer | None = None,
        data_patcher: LiveOptDataPatcher | None = None,
        patcher: LiveOptWorkbenchPatcher | None = None,
        restart_builder: ScaffoldRestartSeedBuilder | None = None,
        semantic_restart_gate: LiveOptSemanticRestartGate | None = None,
        public_update_history: list[dict[str, Any]] | None = None,
    ):
        self.project = project
        self.public_context = copy.deepcopy(public_context or {})
        self.result = result
        self.localizer = localizer or LiveOptUpdateLocalizer(model=project.trace.model)
        self.data_patcher = data_patcher or LiveOptDataPatcher(model=project.trace.model)
        self.patcher = patcher or LiveOptWorkbenchPatcher(model=project.trace.model)
        self.restart_builder = restart_builder or ScaffoldRestartSeedBuilder()
        self.semantic_restart_gate = semantic_restart_gate
        self.current_slots = {"setup.py": project.setup_code, "fitness.py": project.fitness_code}
        self.history: list[DynamicScaffoldStage] = []
        self.public_update_history = copy.deepcopy(public_update_history or [])

    def update(
        self,
        *,
        update_id: str,
        natural_language_update: str,
        public_context: dict[str, Any] | None = None,
        config: EvolutionConfig | None = None,
        impact: DynamicUpdateImpact | dict[str, Any] | None = None,
        force_restart_skill: str | None = None,
        disable_lsm: bool = False,
        stateful_record: bool = False,
        memory_view: str = "full",
        regenerate_typed_workbench: bool = False,
        smoke_test: bool = True,
        max_patch_repairs: int = 3,
    ) -> DynamicScaffoldStage:
        memory_view = validate_memory_view(memory_view)
        if disable_lsm and stateful_record:
            raise ValueError("disable_lsm and stateful_record are mutually exclusive")
        if memory_view != "full" and (disable_lsm or stateful_record):
            raise ValueError(
                "memory_view controls cannot be combined with disable_lsm or stateful_record"
            )
        started = time.perf_counter()
        previous_public_context = copy.deepcopy(self.public_context)
        new_context = normalize_public_context_tables(copy.deepcopy(public_context if public_context is not None else self.public_context))
        # The matched Stateful Record control keeps ordinary public state but
        # removes LSM's accepted-search summary and compatibility evidence from
        # semantic localization.  Its previous accepted public output may still
        # seed a pre-declared warm restart below; no population probe is run.
        if disable_lsm or stateful_record:
            previous_result_for_memory = None
            public_history_for_memory = [] if disable_lsm else self.public_update_history
            accepted_result_for_binding = None
        else:
            previous_result_for_memory = (
                self.result if memory_view_exposes_accepted(memory_view) else None
            )
            public_history_for_memory = (
                self.public_update_history if memory_view_exposes_ledger(memory_view) else []
            )
            # Binding queries may inspect only the committed representative,
            # never the search population or archive.  The restart path below
            # remains unchanged across memory-view controls.
            accepted_result_for_binding = (
                accepted_result_record(self.result, pareto=False)
                if memory_view_exposes_accepted(memory_view)
                else None
            )
        previous_result_for_restart = None if disable_lsm else self.result
        if stateful_record:
            objective_names = list((self.project.problem_spec or {}).get("objective_names") or [])
            previous_result_for_restart = accepted_result_record(self.result, pareto=len(objective_names) > 1)
        if impact is None:
            impact, localizer_trace = self.localizer.classify(
                natural_language_update=natural_language_update,
                project=self.project,
                public_context=new_context,
                previous_result=previous_result_for_memory,
                public_update_history=public_history_for_memory,
            )
        elif isinstance(impact, dict):
            impact = DynamicUpdateImpact.from_mapping(impact)
            localizer_trace = ScaffoldTrace(model="provided_impact")
        else:
            localizer_trace = ScaffoldTrace(model="provided_impact")
        contract_repair_slots = _slots_with_hardcoded_public_entity_ids(self.current_slots, new_context)
        if contract_repair_slots:
            raw = dict(impact.raw)
            raw["contract_repair_slots"] = contract_repair_slots
            impact = replace(
                impact,
                patch_setup=impact.patch_setup or "setup.py" in contract_repair_slots,
                patch_fitness=impact.patch_fitness or "fitness.py" in contract_repair_slots,
                raw=raw,
            )
        if regenerate_typed_workbench:
            raw = dict(impact.raw)
            raw["typed_full_regeneration_control"] = True
            raw["patch_setup"] = True
            raw["patch_fitness"] = True
            impact = replace(impact, patch_setup=True, patch_fitness=True, raw=raw)
        data_patch_payload: dict[str, Any] = {}
        data_patch_trace = ScaffoldTrace(model="data_patch_not_used")
        if impact.data_update and public_context is None:
            new_context, data_patch_trace, data_patch_payload = self.data_patcher.patch_context(
                public_context=new_context,
                natural_language_update=natural_language_update,
                project=self.project,
                max_patch_repairs=max_patch_repairs,
                public_update_history=public_history_for_memory,
            )
            new_context = normalize_public_context_tables(new_context)
        patch_trace = ScaffoldTrace(model=self.patcher.model)
        previous_error = ""
        project = self.project
        patch_base_slots = dict(self.current_slots)
        patched_slots = dict(patch_base_slots)
        for attempt in range(max(1, int(max_patch_repairs) + 1)):
            try:
                patched_slots, attempt_trace = self.patcher.patch_slots(
                    current_slots=patch_base_slots,
                    natural_language_update=natural_language_update,
                    impact=impact,
                    public_context=new_context,
                    previous_error=previous_error,
                )
                patch_trace.prompts.extend(attempt_trace.prompts)
                patch_trace.raw_responses.extend(attempt_trace.raw_responses)
                patch_trace.usage.extend(attempt_trace.usage)
                patch_trace.errors.extend(attempt_trace.errors)
                patch_trace.latency_seconds += attempt_trace.latency_seconds
                project = compile_scaffold_project(self.project.task_id, new_context, patched_slots, patch_trace)
                contract_errors = dynamic_patch_contract_errors(
                    natural_language_update=natural_language_update,
                    impact=impact,
                    project=project,
                    data_patch=data_patch_payload,
                    public_context=new_context,
                )
                if contract_errors:
                    raise ValueError("\n".join(contract_errors))
                if smoke_test:
                    project.run(EvolutionConfig(population_size=6, generations=1, seed=0, archive_limit=6))
                break
            except Exception as exc:  # noqa: BLE001
                if is_llm_quota_limit_error(exc):
                    raise
                previous_error = f"{type(exc).__name__}: {exc}"
                patch_trace.errors.append(previous_error)
                if attempt >= max_patch_repairs:
                    raise ValueError("dynamic patch repair failed: " + previous_error) from exc
        patch_trace.prompts = localizer_trace.prompts + data_patch_trace.prompts + patch_trace.prompts
        patch_trace.raw_responses = localizer_trace.raw_responses + data_patch_trace.raw_responses + patch_trace.raw_responses
        patch_trace.usage = localizer_trace.usage + data_patch_trace.usage + patch_trace.usage
        patch_trace.errors = localizer_trace.errors + data_patch_trace.errors + patch_trace.errors
        patch_trace.latency_seconds += localizer_trace.latency_seconds + data_patch_trace.latency_seconds
        raw_binding_queries = (impact.raw or {}).get("state_binding_queries")
        try:
            state_binding_queries = normalize_state_binding_queries(raw_binding_queries)
            state_bindings, state_binding_diagnostics = materialize_state_bindings(
                state_binding_queries,
                accepted_result=accepted_result_for_binding,
                segments=project.segments,
            )
        except ValueError as exc:
            state_binding_queries = []
            state_bindings = []
            state_binding_diagnostics = {
                "query_count": 0,
                "materialized_count": 0,
                "locked_assignment_count": 0,
                "errors": [f"{type(exc).__name__}: {exc}"],
            }
        if state_binding_diagnostics["errors"]:
            patch_trace.errors.extend(state_binding_diagnostics["errors"])
        impact_raw = dict(impact.raw)
        impact_raw["state_binding_queries"] = copy.deepcopy(state_binding_queries)
        impact_raw["materialized_state_bindings"] = copy.deepcopy(state_bindings)
        impact_raw["state_binding_diagnostics"] = copy.deepcopy(state_binding_diagnostics)
        impact_raw["state_binding_memory_view"] = memory_view
        impact = replace(impact, raw=impact_raw)
        cfg = config or EvolutionConfig()
        objective_shift = None
        semantic_decision: SemanticRestartDecision | None = None
        semantic_trace = ScaffoldTrace(model="semantic_restart_gate_not_used")
        if (
            self.semantic_restart_gate is not None
            and not force_restart_skill
            and not disable_lsm
            and not stateful_record
        ):
            semantic_decision, semantic_trace = self.semantic_restart_gate.decide(
                update_id=update_id,
                natural_language_update=natural_language_update,
                previous_public_context=previous_public_context,
                public_context=new_context,
                previous_project=self.project,
                project=project,
            )
            patch_trace.prompts.extend(semantic_trace.prompts)
            patch_trace.raw_responses.extend(semantic_trace.raw_responses)
            patch_trace.usage.extend(semantic_trace.usage)
            patch_trace.errors.extend(semantic_trace.errors)
            patch_trace.latency_seconds += semantic_trace.latency_seconds
        if force_restart_skill:
            impact = impact.with_restart_skill(force_restart_skill)
        elif stateful_record:
            impact = impact.with_restart_skill(
                "warm_restart_v1" if previous_result_for_restart is not None else "full_restart_v1",
                reason=(
                    "Stateful Record ablation: fixed warm seeding from the previous accepted public output; "
                    "LSM population probes, compatibility statistics, and adaptive restart are unavailable"
                ),
            )
        elif disable_lsm:
            impact = impact.with_restart_skill(
                "full_restart_v1",
                reason="w/o LSM ablation: previous accepted search state and archive are hidden from localization and restart",
            )
        else:
            impact = select_dynamic_restart_from_semantic_evidence(
                impact=impact,
                semantic_decision=semantic_decision,
            )
        initial_genomes, restart_metadata = self.restart_builder.build(
            restart_skill=impact.restart_skill,
            previous_result=previous_result_for_restart,
            segments=project.segments,
            population_size=cfg.population_size,
            seed=cfg.seed,
            evaluate=project.evaluate,
            data=project.data,
            objective_shift=None if force_restart_skill else objective_shift,
        )
        # All memory-view arms receive the same restart population.  Bindings
        # are attached only after restart seeds have been constructed from the
        # common, unmodified Workbench and the same previous search result.
        project = apply_state_bindings(project, state_bindings)
        result = project.run(cfg, initial_genomes=initial_genomes)
        restart_metadata = dict(restart_metadata)
        restart_metadata["data_patch"] = data_patch_payload
        restart_metadata["lsm_disabled"] = bool(disable_lsm)
        restart_metadata["memory_mode"] = "stateful_record" if stateful_record else ("none" if disable_lsm else "lsm")
        restart_metadata["state_binding_memory_view"] = memory_view
        restart_metadata["state_binding_queries"] = copy.deepcopy(state_binding_queries)
        restart_metadata["state_bindings"] = copy.deepcopy(state_bindings)
        restart_metadata["state_binding_diagnostics"] = copy.deepcopy(state_binding_diagnostics)
        restart_metadata["stateful_record_fields"] = (
            ["public_update_history", "committed_public_data_patches", "previous_accepted_public_output"]
            if stateful_record
            else []
        )
        restart_metadata["semantic_restart_gate"] = (
            semantic_decision.to_record() if semantic_decision is not None else {}
        )
        restart_metadata["restart_selection_rule"] = (
            "forced_restart_skill"
            if force_restart_skill
            else "stateful_record_fixed_warm"
            if stateful_record
            else "without_lsm_full_restart"
            if disable_lsm
            else "verified_semantic_full_else_fixed_warm"
        )
        result.metadata = dict(result.metadata)
        result.metadata["restart"] = restart_metadata
        stage = DynamicScaffoldStage(
            update_id=update_id,
            natural_language_update=natural_language_update,
            impact=impact,
            project=project,
            result=result,
            initial_genomes=initial_genomes,
            restart_metadata=restart_metadata,
            patch_trace=patch_trace,
            latency_seconds=time.perf_counter() - started,
        )
        self.project = project
        self.public_context = new_context
        self.current_slots = patched_slots
        self.result = result
        self.history.append(stage)
        self.public_update_history.append(
            {
                "update_id": update_id,
                "natural_language_update": natural_language_update,
                "public_data_patch": copy.deepcopy(data_patch_payload),
            }
        )
        return stage


def accepted_result_record(result: EvolutionResult | None, *, pareto: bool | None = None) -> EvolutionResult | None:
    """Remove non-committed population state for the Stateful Record control.

    Scalar stages expose only the committed best candidate. Pareto stages
    expose the committed nondominated archive. Candidate genomes are retained
    only for accepted outputs because the unchanged typed Workbench needs their
    executable representation when coercing them into fixed warm seeds.
    """

    if result is None:
        return None
    selection = str((result.metadata or {}).get("selection") or "").lower()
    best_objectives = list(result.best.result.objectives or []) if result.best and result.best.result else []
    is_pareto = bool(pareto) if pareto is not None else (selection == "nsga2" and len(best_objectives) > 1)
    accepted = list(result.archive or []) if is_pareto else [result.best]
    if not accepted:
        accepted = [result.best]
    return EvolutionResult(
        best=result.best,
        population=[] if is_pareto else accepted,
        archive=accepted if is_pareto else [],
        history=[],
        metadata={
            "selection": "nsga2" if is_pareto else "scalar_ga",
            "stateful_record": True,
            "accepted_candidate_count": len(accepted),
        },
    )


def build_update_localizer_prompt(
    *,
    natural_language_update: str,
    project: ScaffoldProject,
    public_context: dict[str, Any],
    previous_result: EvolutionResult | None,
    public_update_history: list[dict[str, Any]] | None = None,
) -> str:
    return "\n".join(
        [
            "Classify the dynamic update for a fixed LiveOpt Workbench.",
            "Return exactly one JSON object with keys:",
            "data_update, patch_setup, patch_fitness, restart_skill, reason, state_binding_queries.",
            f"Allowed restart_skill values: {', '.join(sorted(RESTART_SKILLS))}.",
            "restart_skill is only an initial hint for traceability. When prior public search state exists, fixed code selects Fixed Warm or Full from public regime evidence. A substantial compiled-state replacement, typed decision-support replacement, or objective-dimension change selects Full; otherwise it selects Fixed Warm.",
            "Absolute objective offsets/scales and direct infeasibility are diagnostics only and cannot independently force Full, because repaired history can remain useful. The selector never runs a trial optimizer and never reads hidden/reference metrics.",
            "Do not infer restart from benchmark ids or hidden metrics. Focus this JSON on whether public data, setup.py, or fitness.py must be patched.",
            "Set state_binding_queries=[] unless the update explicitly asks to lock or preserve assignment decisions across stages.",
            "For an explicit demand-to-resource lock, emit {\"kind\":\"lock_assignment\",\"segment\":<typed assignment segment>,\"assignments\":{<demand>:<resource>},\"depends_on\":[\"event_ledger\"]}.",
            "For 'preserve the assignments currently on resource R', emit {\"kind\":\"preserve_resource_assignments\",\"segment\":<typed assignment segment>,\"resource_id\":R,\"depends_on\":[\"accepted_output\"]}. Fixed code, not the language model, resolves the committed assignments.",
            "For 'preserve the current assignments of demands D', emit {\"kind\":\"preserve_demand_assignments\",\"segment\":<typed assignment segment>,\"demands\":[D...],\"depends_on\":[\"accepted_output\"]}. If D is identified by a prior event, list both event_ledger and accepted_output.",
            "If the resource is identified through a prior public event and its current assignments must be preserved, list both event_ledger and accepted_output in depends_on.",
            "Never enumerate remembered demand-to-resource pairs inside a preserve query; fixed code resolves those pairs from the committed decision.",
            "For an assignment lock or cross-stage assignment hold, state_binding_queries is the sole representation: set patch_setup=false and patch_fitness=false unless the same update independently changes the encoding, objective, or a non-binding constraint. Never substitute a slot patch or segment-domain restriction for a typed state-binding query.",
            "Use patch_setup only when search segments/data extraction must change.",
            "If public availability, active flags, eligibility, required/blocked ids, or resource membership change the set of selectable decision ids, set patch_setup=true so the search segments are rebuilt from the current public tables.",
            "Also use patch_setup when the current segment signature has an assignment segment plus a binary/int/choice segment that opens/enables/selects the same resources, but the assignment segment lacks resource_open_gate metadata. Add the metadata instead of relying on fitness penalties to discover open-resource consistency.",
            "Use patch_fitness when objectives, constraints, penalties, decode, or solution reporting must change.",
            "If public tables changed but existing setup.py loops over public_context, set data_update=true and patch_setup=false.",
            "If the update explicitly changes any public table value, set data_update=true even when patch_setup or patch_fitness is also needed. Examples include coordinates, availability, capacities, emissions, costs, demands, priorities, due times, deadlines, policy weights, objective coefficients, and active flags.",
            "Never use a code patch as a substitute for public data changes: setup.py and fitness.py must read the same updated public_context that the verifier and hidden evaluator will apply.",
            "When availability/active/eligibility changes remove resources from use, generated setup.py must exclude those resources from assignment domains; generated fitness.py should still penalize invalid legacy ids defensively.",
            "",
            "Current segment signature:",
            json.dumps([segment.__dict__ for segment in project.segments], ensure_ascii=False, sort_keys=True),
            "",
            "Current public context summary:",
            json.dumps(_public_context_summary(public_context), ensure_ascii=False, sort_keys=True),
            "",
            "Previous accepted decision (the search population and archive are not exposed):",
            json.dumps(_previous_result_summary(previous_result), ensure_ascii=False, sort_keys=True),
            "",
            "Prior public event/reference ledger (public updates and committed public patches only):",
            json.dumps(_compact_public_update_history(public_update_history), ensure_ascii=False, sort_keys=True),
            "",
            "Natural-language update:",
            natural_language_update.strip(),
        ]
    )


def build_scaffold_patch_prompt(
    *,
    current_slots: dict[str, str],
    natural_language_update: str,
    impact: DynamicUpdateImpact,
    public_context: dict[str, Any],
    previous_error: str = "",
) -> str:
    requested = []
    if impact.patch_setup:
        requested.append("setup.py")
    if impact.patch_fitness:
        requested.append("fitness.py")
    scoring_text = _public_objective_text_for_prompt(public_context) if isinstance(public_context, dict) else ""
    full_regeneration = bool((impact.raw or {}).get("typed_full_regeneration_control"))
    regeneration_instructions = [
        "This is the typed full-regeneration control: return complete standalone replacements for both slots, not snippets or incremental edits.",
        "Use the current slots only as an interface/contract reference. Reconstruct every required behavior from the current public context and scoring rules.",
        "setup.py must define build_problem(public_context). fitness.py must define evaluate(genome, data).",
    ] if full_regeneration else []
    return "\n".join(
        [
            "Patch only the requested slots for this dynamic optimization update.",
            *regeneration_instructions,
            "Keep the framework-owned GA/NSGA-II runtime unchanged.",
            "Do not hard-code entity IDs; loop over public_context/data produced by setup.py.",
            "Use exact public table columns. Do not invent renamed fields such as *_id, *_code, max_*_limit, or other aliases unless setup.py explicitly maps them from visible public columns and fitness.py reads only those mapped fields.",
            "Do not make an objective term depend on a public column that is absent from the visible schema. If a public row lacks an optional qualifier such as shift, room, or time_slot, apply the row at the coarser visible level described by the scoring rules instead of dropping it.",
            "All submitted solution identifiers must be scalar public IDs, not full row dicts/lists/objects; keep row details in data and write only ids into fields such as vehicle, resource, machine, worker, order, task, job, item, or *_id.",
            "Current public_context is already after any data patch.",
            "Preserve the public optimization contract. If it says objective_mode='multi_objective', keep solver_mode='moea', keep objective_names exactly as specified, and keep fitness.py returning the separate objective vector in that order. Do not replace a Pareto objective vector with one scalarized cost, and do not put literal constant dimensions such as 0 or 0.0 in objectives=[...].",
            "If the contract lists objective_terms, compute every listed term from public data and the current genome/solution. Do not replace required terms with a coarse proxy or a stage-specific private objective.",
            "If the contract lists required_diagnostics or terms marked required_diagnostic, return those component values in penalty_result(..., diagnostics={...}) using the exact public names.",
            "If public_context contains new scalar policy values, setup.py must copy them into data and fitness.py must read them from data; do not hard-code update constants.",
            "Preserve the user-visible plan output format and search-space requirements from the scoring rules unless the update explicitly changes them.",
            "If the update allows assignment demands to be skipped, unassigned, optional, or left out, setup.py must use optional_assignment or allow_none=True, and fitness.py must handle None according to the public penalty/policy.",
            "If setup.py has an assignment segment and a separate binary/int/choice segment for open/active/selected resources, add assignment metadata {'resource_open_gate': {'segment': '<gate_segment_name>', 'resources': resource_ids, 'open_value': 1}}. Do not encode this as problem-specific fitness-only behavior.",
            "If patch_setup is requested because the search space changed, the returned setup.py must visibly change the segment contract.",
            "Return only requested code blocks using headings like ### fitness.py.",
            f"Requested slots: {', '.join(requested)}.",
            f"Restart skill selected outside code patch: {impact.restart_skill}. Do not implement restart logic inside the slots.",
            "",
            "Impact classification:",
            json.dumps(impact.raw or impact.__dict__, ensure_ascii=False, sort_keys=True),
            "",
            "Public context summary:",
            json.dumps(_public_context_summary(public_context), ensure_ascii=False, sort_keys=True),
            "",
            "Scoring rules visible to the user:",
            scoring_text or "(same as the current user request)",
            "",
            "Current user-visible public context after data patch:",
            json.dumps(_public_context_for_prompt(public_context), ensure_ascii=False, sort_keys=True),
            "",
            "Natural-language update:",
            natural_language_update.strip(),
            "",
            "Previous error feedback:" if previous_error else "",
            previous_error.strip(),
            "",
            "Current setup.py:",
            "```python",
            current_slots.get("setup.py", "").strip(),
            "```",
            "",
            "Current fitness.py:",
            "```python",
            current_slots.get("fitness.py", "").strip(),
            "```",
        ]
    )


def build_data_patch_prompt(
    *,
    public_context: dict[str, Any],
    natural_language_update: str,
    project: ScaffoldProject,
    previous_error: str = "",
    previous_patch: dict[str, Any] | None = None,
    public_update_history: list[dict[str, Any]] | None = None,
) -> str:
    repair_feedback = []
    if previous_error:
        repair_feedback = [
            "",
            "Previous patch attempt failed. Return a corrected JSON patch only.",
            "Failure feedback:",
            previous_error.strip(),
            "Previous patch JSON:",
            json.dumps(previous_patch or {}, ensure_ascii=False, sort_keys=True),
        ]
    return "\n".join(
        [
            "Convert the natural-language update into a structured public_context data patch.",
            "Do not modify setup.py, fitness.py, solver code, hidden data, or objective logic.",
            "Data structure contract:",
            '- The writable data root is always public_context["tables"].',
            "- Every public table is a list of row objects: public_context['tables'][table_name] == list[dict].",
            "- Do not write public_data, public_data.tables, csv_tables, hidden data, or benchmark-specific paths.",
            "- For a singleton table such as policy/settings/global_params, still patch the table as a one-row list.",
            "- Use path ['tables', '<table_name>'] for update_row, append_row, delete_row, and replace_table.",
            "- Use path ['tables', '<table_name>', '<field>'] only for set_value/replace_value on a singleton table field.",
            "- Preserve row fields not mentioned by the update; values should be JSON scalars, not nested row wrappers.",
            "- Preserve exact public column names in appended/updated rows. Do not invent *_id or other alias fields when the visible table column has a different name.",
            "- Use the public optimization contract to decide whether an update touches policy/settings/objective weights, soft penalties, or table rows. Never invent hidden scoring fields.",
            "- Include every public table value explicitly changed by the natural-language update. Code patches may adapt how data are used, but they do not replace this data patch.",
            "Return exactly one JSON object with this shape:",
            '{"operations": [{"op": "update_row|append_row|delete_row|set_value|replace_value|replace_table", "path": ["tables", "jobs"], "match": {"id": "A"}, "values": {"hours": 3}}], "reason": "..."}',
            "Supported operations:",
            "- update_row: path points to a list of dict rows; match selects rows; values are merged into matching rows.",
            "- append_row: path points to a list; row is appended. Use row, or values if the row fields are written there.",
            "- delete_row: path points to a list of dict rows; match selects rows to remove.",
            "- set_value or replace_value: path points to a nested key; value replaces it.",
            "- replace_table: path points to a table/list; value replaces the table.",
            "Use only public_context['tables'] keys and public table columns visible below.",
            "Preserve numeric and boolean scalar types. Write 3, 4.5, true, false rather than string versions.",
            "",
            "Current segment signature:",
            json.dumps([segment.__dict__ for segment in project.segments], ensure_ascii=False, sort_keys=True),
            "",
            "Current table schema summary:",
            json.dumps(_public_context_summary(public_context), ensure_ascii=False, sort_keys=True),
            "",
            "Scoring rules visible to the user:",
            _public_objective_text_for_prompt(public_context) or "(same as the current user request)",
            "",
            "Current public_context:",
            json.dumps(_public_context_for_prompt(public_context), ensure_ascii=False, sort_keys=True),
            "",
            "Prior public event/reference ledger (use it to resolve phrases such as 'the item mentioned earlier'):",
            json.dumps(_compact_public_update_history(public_update_history), ensure_ascii=False, sort_keys=True),
            "",
            "Natural-language update:",
            natural_language_update.strip(),
            *repair_feedback,
        ]
    )


def _compact_public_update_history(history: list[dict[str, Any]] | None, *, limit: int = 12) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in list(history or [])[-limit:]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "update_id": str(item.get("update_id") or ""),
                "natural_language_update": str(item.get("natural_language_update") or item.get("public_update") or ""),
                "public_data_patch": copy.deepcopy(item.get("public_data_patch") or {}),
            }
        )
    return compact


def apply_public_context_patch(public_context: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    if isinstance(patch.get("public_context"), dict):
        return normalize_public_context_tables(copy.deepcopy(patch["public_context"]))
    patched = normalize_public_context_tables(copy.deepcopy(public_context))
    operations = patch.get("operations") or patch.get("patches") or []
    if not isinstance(operations, list):
        raise ValueError("data patch operations must be a list")
    for operation in operations:
        if not isinstance(operation, dict):
            raise ValueError("each data patch operation must be an object")
        apply_public_context_operation(patched, operation)
        normalize_public_context_tables(patched)
    return normalize_public_context_tables(patched)


def apply_public_context_operation(public_context: dict[str, Any], operation: dict[str, Any]) -> None:
    op = str(operation.get("op") or "").strip()
    normalize_public_context_tables(public_context)
    path = _resolve_public_context_path(public_context, _coerce_path(operation.get("path")))
    if not op:
        raise ValueError("data patch operation is missing op")
    if not path:
        raise ValueError("data patch operation is missing path")
    if op in {"set_value", "replace_value"}:
        if _is_singleton_table_field_path(public_context, path):
            table = _get_path_value(public_context, path[:2])
            field = path[2]
            if not table:
                table.append({})
            current = table[0].get(field)
            table[0][field] = _coerce_patch_scalar(operation.get("value"), current, field)
        else:
            current = _get_path_value(public_context, path) if _path_exists(public_context, path) else None
            _set_path_value(public_context, path, _coerce_patch_scalar(operation.get("value"), current, path[-1]))
        return
    if op == "replace_table":
        value = operation.get("value")
        if isinstance(value, dict) and isinstance(value.get("rows"), list):
            value = value["rows"]
        if isinstance(value, dict):
            value = [value]
        if not isinstance(value, list):
            raise ValueError("replace_table requires list value or singleton row object")
        existing = _get_path_value(public_context, path) if _path_exists(public_context, path) else []
        exemplar = _first_row(existing)
        _set_path_value(public_context, path, [_coerce_patch_mapping(row if isinstance(row, dict) else {"value": row}, exemplar) for row in value])
        return
    target = _get_path_value(public_context, path)
    if isinstance(target, dict) and _is_table_path(path):
        target = [_coerce_patch_mapping(target)]
        _set_path_value(public_context, path, target)
    if not isinstance(target, list):
        raise ValueError(f"{op} requires path to a list, got {type(target).__name__}")
    if op == "append_row":
        row = operation.get("row")
        if row is None:
            row = operation.get("values")
        if not isinstance(row, dict):
            raise ValueError("append_row requires row object")
        target.append(_coerce_patch_mapping(row, _first_row(target)))
        return
    match = operation.get("match")
    if not isinstance(match, dict) or not match:
        raise ValueError(f"{op} requires non-empty match object")
    matched = [row for row in target if isinstance(row, dict) and _row_matches(row, match)]
    if op == "update_row":
        values = operation.get("values")
        if not isinstance(values, dict):
            raise ValueError("update_row requires values object")
        if not matched and operation.get("upsert"):
            target.append(_coerce_patch_mapping({**copy.deepcopy(match), **copy.deepcopy(values)}, _first_row(target)))
            return
        if not matched:
            raise ValueError(f"update_row matched no rows at path {path!r}")
        for row in matched:
            row.update(_coerce_patch_mapping(values, row))
        return
    if op == "delete_row":
        if not matched:
            raise ValueError(f"delete_row matched no rows at path {path!r}")
        target[:] = [row for row in target if not (isinstance(row, dict) and _row_matches(row, match))]
        return
    raise ValueError(f"unsupported data patch op: {op}")


def normalize_public_context_tables(public_context: dict[str, Any]) -> dict[str, Any]:
    """Normalize public tables to the generic list-of-dicts runtime contract."""
    if not isinstance(public_context, dict):
        raise ValueError("public_context must be an object")
    tables = public_context.get("tables")
    if tables is None:
        legacy = public_context.get("public_data")
        if isinstance(legacy, dict):
            tables = legacy.get("tables") if isinstance(legacy.get("tables"), dict) else legacy
        elif isinstance(public_context.get("csv_tables"), dict):
            tables = {}
        else:
            tables = {}
        public_context["tables"] = tables
    if not isinstance(tables, dict):
        raise ValueError("public_context['tables'] must be an object mapping names to row lists")
    for name, value in list(tables.items()):
        tables[name] = _normalize_table_value(value)
    return public_context


def _normalize_table_value(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        value = value["rows"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        value = [{"value": value}]
    rows: list[dict[str, Any]] = []
    for row in value:
        if isinstance(row, dict):
            rows.append(_coerce_patch_mapping(row))
        else:
            rows.append({"value": _coerce_patch_scalar(row)})
    return rows


def candidate_genomes(result: EvolutionResult) -> list[Candidate]:
    candidates = [candidate for candidate in list(result.archive) + list(result.population) if isinstance(candidate.genome, dict)]
    candidates.sort(key=_candidate_rank_key)
    return candidates


def dynamic_patch_contract_errors(
    *,
    natural_language_update: str,
    impact: DynamicUpdateImpact,
    project: ScaffoldProject,
    data_patch: dict[str, Any],
    public_context: dict[str, Any] | None = None,
) -> list[str]:
    text = " ".join(
        [
            natural_language_update,
            impact.reason,
            json.dumps(impact.raw, ensure_ascii=False),
            json.dumps(data_patch, ensure_ascii=False),
        ]
    ).lower()
    errors = []
    update_text = natural_language_update.lower()
    optional_terms = [
        "unassigned",
        "unassign",
        "optional assignment",
        "may be skipped",
        "can be skipped",
        "skip the job",
        "skip the task",
        "skip the order",
        "left unassigned",
        "left out",
    ]
    if any(term in update_text for term in optional_terms):
        assignment_segments = [segment for segment in project.segments if segment.kind in {"assignment", "optional_assignment"}]
        if assignment_segments and not any(segment.kind == "optional_assignment" or segment.allow_none for segment in assignment_segments):
            errors.append(
                "The update allows demands to be unassigned/skipped, but setup.py still declares mandatory assignment. "
                "Use optional_assignment or allow_none=True for the affected assignment segment."
            )
        if "none" not in project.fitness_code.lower():
            errors.append("The update allows unassigned/skipped demands, but fitness.py does not visibly handle None/unassigned decisions.")
    hardcoded_slots = _slots_with_hardcoded_public_entity_ids(
        {"setup.py": project.setup_code, "fitness.py": project.fitness_code},
        public_context or {},
    )
    if hardcoded_slots:
        details = "; ".join(f"{slot}: {', '.join(values)}" for slot, values in sorted(hardcoded_slots.items()))
        errors.append(
            "Generated Workbench slots hard-code public entity identifiers "
            f"({details}). Read and loop over public tables instead of embedding stage-specific IDs."
        )
    return errors


def _slots_with_hardcoded_public_entity_ids(
    slots: dict[str, str],
    public_context: dict[str, Any],
) -> dict[str, list[str]]:
    entity_ids = _public_entity_ids(public_context)
    if not entity_ids:
        return {}
    violations: dict[str, list[str]] = {}
    for slot_name, code in slots.items():
        if not isinstance(code, str) or not code.strip():
            continue
        try:
            tree = ast.parse(code)
        except SyntaxError:
            continue
        literals = sorted(
            {
                node.value.strip()
                for node in ast.walk(tree)
                if isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and node.value.strip() in entity_ids
            }
        )
        if literals:
            violations[slot_name] = literals
    return violations


def _public_entity_ids(value: Any) -> set[str]:
    entity_ids: set[str] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                key_text = str(key).lower()
                if (
                    key_text == "id"
                    or key_text.endswith("_id")
                    or key_text.endswith("_code")
                ) and isinstance(child, (str, int)):
                    identifier = str(child).strip()
                    if INSTANCE_ENTITY_LITERAL.fullmatch(identifier):
                        entity_ids.add(identifier)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    entity_ids.discard("")
    return entity_ids


def coerce_genome(genome: dict[str, Any], segments: list[SegmentSpec]) -> dict[str, Any]:
    return {segment.name: coerce_segment_value(genome.get(segment.name), segment, idx) for idx, segment in enumerate(segments)}


def coerce_segment_value(value: Any, segment: SegmentSpec, offset: int = 0) -> Any:
    if segment.kind == "real_vector":
        items = list(value) if isinstance(value, list) else []
        return [_clip(float(items[idx]) if idx < len(items) else _mid(segment, idx), _bound(segment.lower, idx), _bound(segment.upper, idx)) for idx in range(segment.length)]
    if segment.kind == "int_vector":
        items = list(value) if isinstance(value, list) else []
        return [int(round(_clip(float(items[idx]) if idx < len(items) else _mid(segment, idx), _bound(segment.lower, idx), _bound(segment.upper, idx)))) for idx in range(segment.length)]
    if segment.kind == "binary_vector":
        items = list(value) if isinstance(value, list) else []
        return [1 if idx < len(items) and bool(items[idx]) else 0 for idx in range(segment.length)]
    if segment.kind == "choice_vector":
        options = list(segment.options)
        items = list(value) if isinstance(value, list) else []
        if not options:
            return []
        return [copy.deepcopy(items[idx]) if idx < len(items) and items[idx] in options else copy.deepcopy(options[(idx + offset) % len(options)]) for idx in range(segment.length)]
    if segment.kind == "permutation":
        allowed = list(segment.values)
        seen = set()
        out = []
        for item in list(value) if isinstance(value, list) else []:
            if item in allowed and item not in seen:
                seen.add(item)
                out.append(copy.deepcopy(item))
        out.extend(copy.deepcopy(item) for item in allowed if item not in seen)
        return out
    if segment.kind in {"assignment", "optional_assignment"}:
        mapping = value if isinstance(value, dict) else {}
        resources = list(segment.resources)
        allowed = set(resources)
        out = {}
        for idx, demand in enumerate(segment.demands):
            old = mapping.get(demand, mapping.get(str(demand)))
            if old in allowed or ((segment.allow_none or segment.kind == "optional_assignment") and old is None):
                out[demand] = copy.deepcopy(old)
            elif resources:
                out[demand] = copy.deepcopy(resources[(idx + offset) % len(resources)])
            else:
                out[demand] = None
        return out
    raise ValueError(f"unsupported segment kind: {segment.kind}")


def filter_feasible_seeds(
    seeds: list[dict[str, Any]],
    evaluate: Callable[[dict[str, Any], dict[str, Any]], Any] | None,
    data: dict[str, Any],
) -> list[dict[str, Any]]:
    if evaluate is None:
        return seeds
    out = []
    for seed in seeds:
        try:
            result = coerce_fitness_result(evaluate(seed, data), seed)
        except Exception:
            continue
        if result.feasible:
            out.append(seed)
    return out


def unique_genomes(genomes: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out = []
    seen = set()
    for genome in genomes:
        key = json.dumps(genome, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(genome)
        if len(out) >= limit:
            break
    return out


def unique_candidate_genomes(candidates: list[Candidate], limit: int) -> list[Candidate]:
    out: list[Candidate] = []
    seen = set()
    for candidate in candidates:
        key = json.dumps(candidate.genome, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        out.append(candidate)
        if len(out) >= limit:
            break
    return out


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("localizer response did not contain a JSON object")
    payload = json.loads(cleaned[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("localizer response JSON must be an object")
    return payload


def _coerce_path(value: Any) -> list[str]:
    if isinstance(value, str):
        path = [part for part in value.replace("/", ".").split(".") if part]
        return _strip_context_root(path)
    if isinstance(value, list):
        return _strip_context_root([str(part) for part in value if str(part)])
    return []


def _strip_context_root(path: list[str]) -> list[str]:
    if path and path[0] in {"public_context", "context", "root"}:
        return path[1:]
    return path


def _resolve_public_context_path(root: dict[str, Any], path: list[str]) -> list[str]:
    if not path:
        return path
    if _path_exists(root, path):
        return path
    if path[0] == "public_data" and "tables" in root:
        candidates = []
        if len(path) >= 2 and path[1] == "tables":
            candidates.append(["tables", *path[2:]])
        if len(path) >= 2:
            candidates.append(["tables", *path[1:]])
        for candidate in candidates:
            if _path_parent_exists(root, candidate) or _path_exists(root, candidate):
                return candidate
    if path[0] == "csv_tables" and "tables" in root and len(path) >= 2:
        candidate = ["tables", *path[1:]]
        if _path_parent_exists(root, candidate) or _path_exists(root, candidate):
            return candidate
    return path


def _is_table_path(path: list[str]) -> bool:
    return len(path) == 2 and path[0] == "tables"


def _is_singleton_table_field_path(root: dict[str, Any], path: list[str]) -> bool:
    if len(path) != 3 or path[0] != "tables":
        return False
    table = root.get("tables", {}).get(path[1]) if isinstance(root.get("tables"), dict) else None
    return isinstance(table, list) and (len(table) <= 1 or isinstance(table[0], dict))


def _first_row(value: Any) -> dict[str, Any]:
    if isinstance(value, list):
        for row in value:
            if isinstance(row, dict):
                return row
    if isinstance(value, dict):
        return value
    return {}


def _coerce_patch_mapping(values: dict[str, Any], exemplar: dict[str, Any] | None = None) -> dict[str, Any]:
    exemplar = exemplar or {}
    out: dict[str, Any] = {}
    for key, value in values.items():
        out[key] = _coerce_patch_scalar(value, exemplar.get(key), str(key))
    return out


def _coerce_patch_scalar(value: Any, exemplar: Any = None, key: str = "") -> Any:
    if isinstance(value, dict):
        exemplar_dict = exemplar if isinstance(exemplar, dict) else {}
        return _coerce_patch_mapping(value, exemplar_dict)
    if isinstance(value, list):
        item_exemplar = exemplar[0] if isinstance(exemplar, list) and exemplar else None
        return [_coerce_patch_scalar(item, item_exemplar, key) for item in value]
    if isinstance(value, str):
        text = value.strip()
        if isinstance(exemplar, bool):
            lowered = text.lower()
            if lowered in {"true", "yes", "1"}:
                return True
            if lowered in {"false", "no", "0"}:
                return False
        if isinstance(exemplar, int) and not isinstance(exemplar, bool):
            try:
                if any(mark in text for mark in [".", "e", "E"]):
                    return float(text)
                return int(float(text))
            except ValueError:
                return value
        if isinstance(exemplar, float):
            try:
                return float(text)
            except ValueError:
                return value
        lowered = text.lower()
        if lowered in {"true", "false"}:
            return lowered == "true"
        if _numeric_key_hint(key) and _looks_numeric(text):
            return float(text) if any(mark in text for mark in [".", "e", "E"]) else int(text)
    return value


def _numeric_key_hint(key: str) -> bool:
    lowered = key.lower()
    hints = {
        "amount",
        "budget",
        "capacity",
        "cost",
        "count",
        "cpu",
        "demand",
        "distance",
        "duration",
        "due",
        "emission",
        "energy",
        "hour",
        "hours",
        "impact",
        "lateness",
        "limit",
        "load",
        "lower",
        "max",
        "mem",
        "memory",
        "min",
        "penalty",
        "price",
        "priority",
        "quantity",
        "qty",
        "rate",
        "risk",
        "size",
        "time",
        "upper",
        "value",
        "weight",
    }
    return any(hint in lowered for hint in hints)


def _looks_numeric(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return bool(text) and not (len(text) > 1 and text.startswith("0") and text[1].isdigit() and "." not in text)


def _path_exists(root: dict[str, Any], path: list[str]) -> bool:
    cursor: Any = root
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            return False
        cursor = cursor[part]
    return True


def _path_parent_exists(root: dict[str, Any], path: list[str]) -> bool:
    if not path:
        return False
    return _path_exists(root, path[:-1])


def _get_path_value(root: dict[str, Any], path: list[str]) -> Any:
    cursor: Any = root
    for part in path:
        if not isinstance(cursor, dict) or part not in cursor:
            raise ValueError(f"path not found: {path!r}")
        cursor = cursor[part]
    return cursor


def _set_path_value(root: dict[str, Any], path: list[str], value: Any) -> None:
    cursor: Any = root
    for part in path[:-1]:
        if not isinstance(cursor, dict):
            raise ValueError(f"path parent is not a dict: {path!r}")
        if part not in cursor or not isinstance(cursor[part], dict):
            cursor[part] = {}
        cursor = cursor[part]
    if not isinstance(cursor, dict):
        raise ValueError(f"path parent is not a dict: {path!r}")
    cursor[path[-1]] = value


def _row_matches(row: dict[str, Any], match: dict[str, Any]) -> bool:
    return all(str(row.get(key)) == str(value) for key, value in match.items())


def _public_context_summary(public_context: dict[str, Any]) -> dict[str, Any]:
    tables = public_context.get("tables") if isinstance(public_context.get("tables"), dict) else {}
    csv_tables = public_context.get("csv_tables") if isinstance(public_context.get("csv_tables"), dict) else {}
    return {
        "keys": sorted(str(key) for key in public_context.keys()),
        "tables": {
            name: {"rows": len(rows), "columns": sorted(rows[0]) if rows and isinstance(rows[0], dict) else []}
            for name, rows in sorted(tables.items())
            if isinstance(rows, list)
        },
        "csv_tables": {name: sorted(meta.keys()) if isinstance(meta, dict) else [] for name, meta in sorted(csv_tables.items())},
        "objective_sense": public_context.get("objective_sense"),
        "multi_objective": public_context.get("multi_objective"),
        "scoring_rules_text": _public_objective_text_for_prompt(public_context),
    }


def _public_context_for_prompt(public_context: dict[str, Any]) -> dict[str, Any]:
    """Keep prompt context user-visible and data-focused."""
    tables = public_context.get("tables") if isinstance(public_context.get("tables"), dict) else {}
    schema = public_context.get("csv_schema") if isinstance(public_context.get("csv_schema"), dict) else {}
    out: dict[str, Any] = {
        "tables": tables,
        "csv_schema": schema,
        "objective_sense": public_context.get("objective_sense"),
        "multi_objective": public_context.get("multi_objective"),
        "scoring_rules_text": _public_objective_text_for_prompt(public_context),
    }
    return out


def _public_objective_text_for_prompt(public_context: dict[str, Any]) -> str:
    text = public_context.get("public_objective_spec_text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    spec = _public_objective_spec_for_prompt(public_context)
    if not spec:
        return ""
    parts: list[str] = []
    names = spec.get("objective_names")
    if names:
        parts.append(f"Objectives or score names: {names}.")
    if spec.get("scalar_formula"):
        parts.append(f"Scoring rule: {spec.get('scalar_formula')}.")
    hard = spec.get("hard_constraints")
    if hard:
        parts.append(f"Feasibility rules: {hard}.")
    return " ".join(parts)


def _public_objective_spec_for_prompt(public_context: dict[str, Any]) -> dict[str, Any]:
    source = public_context.get("public_objective_spec")
    if isinstance(source, dict) and source:
        return source
    contract = public_context.get("optimization_contract")
    if not isinstance(contract, dict):
        return {}
    public_keys = {
        "objective_mode",
        "solution_cardinality",
        "objective_sense",
        "objective_names",
        "hard_constraints",
        "objective_terms",
        "scalar_formula",
        "required_diagnostics",
        "diagnostics",
        "auxiliary_metrics",
        "update_contract",
        "instruction",
    }
    return {key: value for key, value in contract.items() if key in public_keys}


def _previous_result_summary(result: EvolutionResult | None) -> dict[str, Any]:
    return accepted_state_prompt_record(result)


def _candidate_rank_key(candidate: Candidate) -> tuple[float, float, str]:
    feasible_penalty = 0.0 if candidate.result and candidate.result.feasible else 1.0
    scalar = candidate.result.scalar if candidate.result else float("inf")
    return feasible_penalty, float(scalar), json.dumps(candidate.genome, ensure_ascii=False, sort_keys=True, default=str)


def _candidate_record(candidate: Candidate | None) -> dict[str, Any]:
    if candidate is None:
        return {}
    result = candidate.result
    return {
        "genome": candidate.genome,
        "rank": candidate.rank,
        "scalar": result.scalar if result else None,
        "objectives": result.objectives if result else [],
        "feasible": result.feasible if result else None,
        "violations": result.violations if result else {},
        "solution": result.solution if result else {},
    }


def _bound(bound: float | int | list[float | int], idx: int) -> float:
    if isinstance(bound, list):
        if not bound:
            return 0.0
        return float(bound[min(idx, len(bound) - 1)])
    return float(bound)


def _mid(segment: SegmentSpec, idx: int) -> float:
    return (_bound(segment.lower, idx) + _bound(segment.upper, idx)) / 2.0


def _clip(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))
