from __future__ import annotations

import copy
import itertools
import math
import random
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from evo2.evaluation.moea_metrics import approximate_hypervolume


SUPPORTED_SEGMENT_KINDS = {
    "real_vector",
    "int_vector",
    "binary_vector",
    "permutation",
    "choice_vector",
    "assignment",
    "optional_assignment",
}

SUPPORTED_VARIATION_MODES = {
    "typed",
    "type_agnostic_resampling",
}


@dataclass(frozen=True)
class SegmentSpec:
    """One composable decision segment.

    The LLM selects these primitives in the Workbench setup slot; the framework
    owns initialization, crossover, and mutation. Problem semantics stay in
    generated data, repair, decode, and fitness code.
    """

    name: str
    kind: str
    length: int = 0
    lower: float | int | list[float | int] = 0
    upper: float | int | list[float | int] = 1
    values: list[Any] = field(default_factory=list)
    options: list[Any] = field(default_factory=list)
    demands: list[Any] = field(default_factory=list)
    resources: list[Any] = field(default_factory=list)
    allow_none: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in SUPPORTED_SEGMENT_KINDS:
            raise ValueError(f"unsupported segment kind: {self.kind}")
        if not self.name:
            raise ValueError("segment name is required")
        if self.kind == "permutation" and not self.values:
            raise ValueError(f"permutation segment {self.name} requires values")
        if self.kind in {"assignment", "optional_assignment"}:
            if not self.demands:
                raise ValueError(f"{self.kind} segment {self.name} requires demands")
            if not self.resources and not self.allow_none and self.kind != "optional_assignment":
                raise ValueError(f"assignment segment {self.name} requires resources")
        if self.kind == "choice_vector" and not self.options:
            raise ValueError(f"choice_vector segment {self.name} requires options")
        if self.kind in {"real_vector", "int_vector", "binary_vector", "choice_vector"} and self.length <= 0:
            raise ValueError(f"{self.kind} segment {self.name} requires positive length")


@dataclass
class FitnessResult:
    scalar: float
    objectives: list[float] = field(default_factory=list)
    feasible: bool = True
    violations: dict[str, Any] = field(default_factory=dict)
    base_scalar: float | None = None
    penalty: float = 0.0
    solution: dict[str, Any] = field(default_factory=dict)
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def with_penalty(
        cls,
        base_scalar: float,
        violations: dict[str, Any] | None = None,
        *,
        objectives: list[float] | None = None,
        penalty_weight: float = 1_000_000.0,
        solution: dict[str, Any] | None = None,
        diagnostics: dict[str, Any] | None = None,
    ) -> "FitnessResult":
        penalty = penalty_weight * violation_amount(violations or {})
        return cls(
            scalar=float(base_scalar) + penalty,
            objectives=list(objectives or []),
            feasible=penalty <= 0.0,
            violations=violations or {},
            base_scalar=float(base_scalar),
            penalty=penalty,
            solution=solution or {},
            diagnostics=diagnostics or {},
        )


@dataclass
class Candidate:
    genome: dict[str, Any]
    result: FitnessResult | None = None
    rank: int = 10**9
    crowding_distance: float = 0.0


@dataclass
class EvolutionConfig:
    population_size: int = 100
    generations: int = 100
    seed: int | None = None
    crossover_rate: float = 0.9
    mutation_rate: float | None = None
    eta_c: float = 15.0
    eta_m: float = 20.0
    variation_mode: str = "typed"
    tournament_size: int = 3
    archive_limit: int = 200
    structured_initialization: bool = True
    exact_enumeration_limit: int = 1_000_000
    selection_mode: str = "auto"
    record_metric_history: bool = False
    record_archive_history: bool = False
    history_interval: int = 1
    history_archive_limit: int = 200
    reference_free_early_stopping: bool = False
    early_stop_min_generations: int = 30
    early_stop_patience: int = 20
    early_stop_hv_epsilon: float = 1e-3
    early_stop_scalar_epsilon: float = 1e-5
    early_stop_epsilon_box: float = 0.01
    early_stop_min_archive_size: int = 3
    history_metric_recorder: Callable[[int, list[Candidate], list[Candidate], bool], dict[str, Any] | None] | None = field(
        default=None,
        repr=False,
        compare=False,
    )


@dataclass
class EvolutionResult:
    best: Candidate
    population: list[Candidate]
    archive: list[Candidate]
    history: list[dict[str, Any]]
    metadata: dict[str, Any]


class _ReferenceFreeEarlyStopper:
    """Convergence monitor that does not read hidden or reference-front data."""

    def __init__(self, cfg: EvolutionConfig):
        self.enabled = bool(cfg.reference_free_early_stopping)
        self.min_generations = max(0, int(cfg.early_stop_min_generations))
        self.patience = max(1, int(cfg.early_stop_patience))
        self.hv_epsilon = max(0.0, float(cfg.early_stop_hv_epsilon))
        self.scalar_epsilon = max(0.0, float(cfg.early_stop_scalar_epsilon))
        self.epsilon_box = max(1e-9, float(cfg.early_stop_epsilon_box))
        self.min_archive_size = max(1, int(cfg.early_stop_min_archive_size))
        self.stale_generations = 0
        self.stop_generation: int | None = None
        self.stop_reason = ""
        self.last_stats: dict[str, Any] = {"enabled": self.enabled}
        self._best_scalar = math.inf
        self._best_internal_hv: float | None = None
        self._best_ideal: tuple[float, ...] | None = None
        self._seen_cells: set[tuple[int, ...]] = set()
        self._observed_low: list[float] | None = None
        self._observed_high: list[float] | None = None
        self._frozen_low: tuple[float, ...] | None = None
        self._frozen_high: tuple[float, ...] | None = None
        self._initialized_multi = False

    def update(self, generation: int, population: list[Candidate], archive: list[Candidate], multi: bool) -> bool:
        if not self.enabled:
            return False
        if multi:
            return self._update_multi(generation, archive or population)
        return self._update_scalar(generation, archive or population)

    def metadata(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "stopped": self.stop_generation is not None,
            "stop_generation": self.stop_generation,
            "stop_reason": self.stop_reason,
            "min_generations": self.min_generations,
            "patience": self.patience,
            "hv_epsilon": self.hv_epsilon,
            "scalar_epsilon": self.scalar_epsilon,
            "epsilon_box": self.epsilon_box,
            "min_archive_size": self.min_archive_size,
            "last_stats": dict(self.last_stats),
        }

    def _update_scalar(self, generation: int, candidates: list[Candidate]) -> bool:
        values = [
            _scalar(candidate)
            for candidate in candidates
            if candidate.result and candidate.result.feasible and math.isfinite(_scalar(candidate))
        ]
        if not values:
            self.last_stats = {
                "enabled": True,
                "mode": "scalar",
                "generation": generation,
                "eligible": False,
                "reason": "no_feasible_candidate",
                "stale_generations": self.stale_generations,
            }
            return False
        best = min(values)
        if best < self._best_scalar:
            denom = max(abs(self._best_scalar), abs(best), 1.0) if math.isfinite(self._best_scalar) else 1.0
            relative_gain = (self._best_scalar - best) / denom if math.isfinite(self._best_scalar) else math.inf
        else:
            relative_gain = 0.0
        if not math.isfinite(self._best_scalar):
            self._best_scalar = best
            self.stale_generations = 0
        elif generation >= self.min_generations and relative_gain <= self.scalar_epsilon:
            self.stale_generations += 1
        else:
            self._best_scalar = min(self._best_scalar, best)
            self.stale_generations = 0
        self.last_stats = {
            "enabled": True,
            "mode": "scalar",
            "generation": generation,
            "eligible": generation >= self.min_generations,
            "best_scalar": best,
            "best_seen_scalar": self._best_scalar,
            "relative_gain": relative_gain if math.isfinite(relative_gain) else None,
            "stale_generations": self.stale_generations,
        }
        if generation >= self.min_generations and self.stale_generations >= self.patience:
            self.stop_generation = generation
            self.stop_reason = "scalar_objective_stalled"
            return True
        return False

    def _update_multi(self, generation: int, candidates: list[Candidate]) -> bool:
        vectors = [
            tuple(_objective_vector(candidate))
            for candidate in candidates
            if candidate.result
            and candidate.result.feasible
            and len(_objective_vector(candidate)) > 1
            and all(math.isfinite(value) for value in _objective_vector(candidate))
        ]
        if not vectors:
            self.last_stats = {
                "enabled": True,
                "mode": "multi",
                "generation": generation,
                "eligible": False,
                "reason": "no_feasible_archive",
                "stale_generations": self.stale_generations,
            }
            return False
        dim = len(vectors[0])
        vectors = [vector for vector in vectors if len(vector) == dim]
        self._update_observed_bounds(vectors)
        if generation < self.min_generations or len(vectors) < self.min_archive_size:
            self.last_stats = {
                "enabled": True,
                "mode": "multi",
                "generation": generation,
                "eligible": False,
                "feasible_archive": len(vectors),
                "objective_dim": dim,
                "stale_generations": self.stale_generations,
            }
            return False
        self._freeze_bounds()
        internal_hv = self._internal_hv(vectors)
        cells = self._epsilon_cells(vectors)
        ideal = tuple(min(vector[idx] for vector in vectors) for idx in range(dim))
        if not self._initialized_multi:
            self._initialized_multi = True
            self._best_internal_hv = internal_hv
            self._best_ideal = ideal
            self._seen_cells = set(cells)
            self.stale_generations = 0
            self.last_stats = self._multi_stats(generation, vectors, internal_hv, cells, ideal, 0.0, len(cells))
            return False
        hv_gain = internal_hv - float(self._best_internal_hv if self._best_internal_hv is not None else internal_hv)
        new_cells = len(cells - self._seen_cells)
        ideal_gain = self._ideal_gain(ideal)
        improved = hv_gain > self.hv_epsilon or new_cells > 0 or ideal_gain > self.hv_epsilon
        if improved:
            self.stale_generations = 0
            self._best_internal_hv = max(float(self._best_internal_hv or 0.0), internal_hv)
            self._seen_cells.update(cells)
            if self._best_ideal is None:
                self._best_ideal = ideal
            else:
                self._best_ideal = tuple(min(old, new) for old, new in zip(self._best_ideal, ideal))
        else:
            self.stale_generations += 1
        self.last_stats = self._multi_stats(generation, vectors, internal_hv, cells, ideal, hv_gain, new_cells)
        self.last_stats["ideal_gain"] = ideal_gain
        if self.stale_generations >= self.patience:
            self.stop_generation = generation
            self.stop_reason = "pareto_archive_stalled"
            return True
        return False

    def _update_observed_bounds(self, vectors: list[tuple[float, ...]]) -> None:
        dim = len(vectors[0])
        if self._observed_low is None or len(self._observed_low) != dim:
            self._observed_low = [math.inf] * dim
            self._observed_high = [-math.inf] * dim
        assert self._observed_high is not None
        for vector in vectors:
            for idx, value in enumerate(vector):
                self._observed_low[idx] = min(self._observed_low[idx], float(value))
                self._observed_high[idx] = max(self._observed_high[idx], float(value))

    def _freeze_bounds(self) -> None:
        if self._frozen_low is not None or self._observed_low is None or self._observed_high is None:
            return
        lows = []
        highs = []
        for low, high in zip(self._observed_low, self._observed_high):
            span = max(high - low, abs(high), abs(low), 1.0)
            lows.append(float(low))
            highs.append(float(high) + 0.05 * span + 1e-9)
        self._frozen_low = tuple(lows)
        self._frozen_high = tuple(highs)

    def _internal_hv(self, vectors: list[tuple[float, ...]]) -> float:
        if self._frozen_low is None or self._frozen_high is None:
            return 0.0
        names = [f"obj_{idx}" for idx in range(len(self._frozen_low))]
        items = [
            {"objectives": {name: float(vector[idx]) for idx, name in enumerate(names)}}
            for vector in vectors
        ]
        ideal = {name: self._frozen_low[idx] for idx, name in enumerate(names)}
        ref = {name: self._frozen_high[idx] for idx, name in enumerate(names)}
        return float(approximate_hypervolume(items, names, ref=ref, ideal=ideal, samples=0))

    def _epsilon_cells(self, vectors: list[tuple[float, ...]]) -> set[tuple[int, ...]]:
        if self._frozen_low is None or self._frozen_high is None:
            return set()
        cells: set[tuple[int, ...]] = set()
        for vector in vectors:
            cell = []
            for idx, value in enumerate(vector):
                denom = max(self._frozen_high[idx] - self._frozen_low[idx], 1e-12)
                normalized = (float(value) - self._frozen_low[idx]) / denom
                cell.append(math.floor(normalized / self.epsilon_box))
            cells.add(tuple(cell))
        return cells

    def _ideal_gain(self, ideal: tuple[float, ...]) -> float:
        if self._best_ideal is None or self._frozen_low is None or self._frozen_high is None:
            return 0.0
        gains = []
        for idx, value in enumerate(ideal):
            denom = max(self._frozen_high[idx] - self._frozen_low[idx], 1e-12)
            gains.append(max(0.0, (self._best_ideal[idx] - value) / denom))
        return max(gains, default=0.0)

    def _multi_stats(
        self,
        generation: int,
        vectors: list[tuple[float, ...]],
        internal_hv: float,
        cells: set[tuple[int, ...]],
        ideal: tuple[float, ...],
        hv_gain: float,
        new_cells: int,
    ) -> dict[str, Any]:
        return {
            "enabled": True,
            "mode": "multi",
            "generation": generation,
            "eligible": True,
            "internal_hv": round(float(internal_hv), 6),
            "hv_gain": round(float(hv_gain), 6),
            "epsilon_cells": len(cells),
            "new_epsilon_cells": int(new_cells),
            "feasible_archive": len(vectors),
            "objective_dim": len(vectors[0]) if vectors else 0,
            "ideal": [round(float(value), 6) for value in ideal],
            "stale_generations": self.stale_generations,
        }


DecodeFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
RepairFn = Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
EvaluateFn = Callable[[dict[str, Any], dict[str, Any]], FitnessResult | dict[str, Any] | float]


@dataclass(frozen=True)
class GenericEvolutionHooks:
    """Untyped candidate operators for the matched Generic Workbench control.

    The artifact owns representation and variation. The framework still owns
    selection, nondominated sorting, archives, accounting, and early stopping.
    """

    initialize: Callable[[dict[str, Any], random.Random], dict[str, Any]]
    evaluate_decode: EvaluateFn
    crossover: Callable[[dict[str, Any], dict[str, Any], dict[str, Any], random.Random], dict[str, Any]]
    mutate: Callable[[dict[str, Any], dict[str, Any], random.Random], dict[str, Any]]
    coerce_repair: Callable[[dict[str, Any], dict[str, Any], random.Random], dict[str, Any]]


def random_genome(segments: Iterable[SegmentSpec], rng: random.Random) -> dict[str, Any]:
    segment_list = list(segments)
    genome = {segment.name: _random_segment(segment, rng) for segment in segment_list}
    return _repair_genome_segments(genome, segment_list, rng)


def crossover_genome(
    parent_a: dict[str, Any],
    parent_b: dict[str, Any],
    segments: Iterable[SegmentSpec],
    rng: random.Random,
    eta_c: float = 15.0,
) -> dict[str, Any]:
    child: dict[str, Any] = {}
    segment_list = list(segments)
    for segment in segment_list:
        a = parent_a.get(segment.name)
        b = parent_b.get(segment.name)
        child[segment.name] = _crossover_segment(segment, a, b, rng, eta_c)
    return _repair_genome_segments(child, segment_list, rng)


def mutate_genome(
    genome: dict[str, Any],
    segments: Iterable[SegmentSpec],
    rng: random.Random,
    mutation_rate: float | None = None,
    eta_m: float = 20.0,
) -> dict[str, Any]:
    segment_list = list(segments)
    mutated = _copy_genome(genome, segment_list)
    default_rate = 1.0 / max(1, sum(max(1, _segment_length(s)) for s in segment_list))
    rate = default_rate if mutation_rate is None else float(mutation_rate)
    for segment in segment_list:
        mutated[segment.name] = _mutate_segment(segment, mutated.get(segment.name), rng, rate, eta_m)
    return _repair_genome_segments(mutated, segment_list, rng)


def type_agnostic_crossover_genome(
    parent_a: dict[str, Any],
    parent_b: dict[str, Any],
    segments: Iterable[SegmentSpec],
    rng: random.Random,
) -> dict[str, Any]:
    """Cross whole segments without using their type-specific structure."""

    segment_list = list(segments)
    child = {
        segment.name: copy.deepcopy(
            (parent_a if rng.random() < 0.5 else parent_b).get(segment.name)
        )
        for segment in segment_list
    }
    return _repair_genome_segments(child, segment_list, rng)


def type_agnostic_mutate_genome(
    genome: dict[str, Any],
    segments: Iterable[SegmentSpec],
    rng: random.Random,
    mutation_rate: float | None = None,
) -> dict[str, Any]:
    """Replace whole segments with valid samples, independent of segment kind."""

    segment_list = list(segments)
    mutated = _copy_genome(genome, segment_list)
    rate = 1.0 / max(1, len(segment_list)) if mutation_rate is None else float(mutation_rate)
    for segment in segment_list:
        if rng.random() < rate:
            mutated[segment.name] = _random_segment(segment, rng)
    return _repair_genome_segments(mutated, segment_list, rng)


def run_evolution(
    segments: list[SegmentSpec],
    evaluate: EvaluateFn,
    *,
    decode: DecodeFn | None = None,
    repair: RepairFn | None = None,
    data: dict[str, Any] | None = None,
    config: EvolutionConfig | None = None,
    initial_genomes: list[dict[str, Any]] | None = None,
) -> EvolutionResult:
    """Run scalar GA or NSGA-II from composable decision segments.

    LLM-generated code only supplies decode/repair/evaluate. The framework
    supplies population creation, classic variation operators, nondominated
    sorting, crowding distance, and archive bookkeeping.
    """

    if not segments:
        raise ValueError("at least one SegmentSpec is required")
    cfg = config or EvolutionConfig()
    selection_mode = str(cfg.selection_mode or "auto").strip().lower()
    if selection_mode not in {"auto", "scalar_ga", "moea"}:
        raise ValueError(f"unsupported selection_mode: {cfg.selection_mode}")
    variation_mode = str(cfg.variation_mode or "typed").strip().lower()
    if variation_mode not in SUPPORTED_VARIATION_MODES:
        raise ValueError(f"unsupported variation_mode: {cfg.variation_mode}")
    rng = random.Random(cfg.seed)
    data = data or {}
    seed_genomes = list(initial_genomes or [])
    if cfg.structured_initialization:
        seed_genomes.extend(_structured_seed_genomes(segments, cfg.population_size))
    population = [
        Candidate(_repair_genome_segments(_copy_genome(genome, segments), segments, rng))
        for genome in seed_genomes[: cfg.population_size]
    ]
    while len(population) < cfg.population_size:
        population.append(Candidate(random_genome(segments, rng)))
    _evaluate_population(population, evaluate, decode, repair, data)
    multi = _selection_is_multi(selection_mode, population)
    if multi:
        population = nsga2_select(population, cfg.population_size)
    else:
        population.sort(key=_scalar_key)
    archive_diagnostics: dict[str, Any] = {}
    archive = _archive(population, [], cfg.archive_limit, diagnostics=archive_diagnostics)
    early_stopper = _ReferenceFreeEarlyStopper(cfg)
    history = [
        _history_row(
            0,
            population,
            multi,
            archive=archive,
            record_metrics=cfg.record_metric_history,
            record_archive=cfg.record_archive_history,
            archive_limit=cfg.history_archive_limit,
            metric_recorder=cfg.history_metric_recorder,
        )
    ]
    early_stopper.update(0, population, archive, multi)
    executed_generations = 0

    for generation in range(1, cfg.generations + 1):
        children: list[Candidate] = []
        while len(children) < cfg.population_size:
            p1 = _tournament(population, rng, cfg.tournament_size, multi)
            p2 = _tournament(population, rng, cfg.tournament_size, multi)
            if rng.random() < cfg.crossover_rate:
                if variation_mode == "typed":
                    genome = crossover_genome(p1.genome, p2.genome, segments, rng, cfg.eta_c)
                else:
                    genome = type_agnostic_crossover_genome(p1.genome, p2.genome, segments, rng)
            else:
                genome = _copy_genome(p1.genome, segments)
            if variation_mode == "typed":
                genome = mutate_genome(genome, segments, rng, cfg.mutation_rate, cfg.eta_m)
            else:
                genome = type_agnostic_mutate_genome(genome, segments, rng, cfg.mutation_rate)
            children.append(Candidate(genome))
        _evaluate_population(children, evaluate, decode, repair, data)
        multi = multi or _selection_is_multi(selection_mode, children)
        if multi:
            population = nsga2_select(population + children, cfg.population_size)
        else:
            population = _scalar_select(population + children, cfg.population_size)
        archive = _archive(population, archive, cfg.archive_limit, diagnostics=archive_diagnostics)
        executed_generations = generation
        should_record_history = (cfg.record_metric_history or cfg.record_archive_history) and (
            generation % max(1, int(cfg.history_interval or 1)) == 0 or generation == cfg.generations
        )
        history.append(
            _history_row(
                generation,
                population,
                multi,
                archive=archive,
                record_metrics=should_record_history and cfg.record_metric_history,
                record_archive=should_record_history and cfg.record_archive_history,
                archive_limit=cfg.history_archive_limit,
                metric_recorder=cfg.history_metric_recorder,
            )
        )
        if early_stopper.update(generation, population, archive, multi):
            if not should_record_history and (cfg.record_metric_history or cfg.record_archive_history):
                history[-1] = _history_row(
                    generation,
                    population,
                    multi,
                    archive=archive,
                    record_metrics=bool(cfg.record_metric_history),
                    record_archive=bool(cfg.record_archive_history),
                    archive_limit=cfg.history_archive_limit,
                    metric_recorder=cfg.history_metric_recorder,
                )
            break

    best = population[0]
    early_stop_metadata = early_stopper.metadata()
    return EvolutionResult(
        best=best,
        population=population,
        archive=archive,
        history=history,
        metadata={
            "selection": "nsga2" if multi else "scalar_ga",
            "selection_mode": selection_mode,
            "variation_mode": variation_mode,
            "population_size": cfg.population_size,
            "generations": cfg.generations,
            "executed_generations": executed_generations,
            "early_stopped": bool(early_stop_metadata.get("stopped")),
            "early_stop": early_stop_metadata,
            "record_metric_history": bool(cfg.record_metric_history),
            "record_archive_history": bool(cfg.record_archive_history),
            "history_interval": int(cfg.history_interval),
            "history_archive_limit": int(cfg.history_archive_limit),
            "archive_diagnostics": dict(archive_diagnostics),
            "segment_kinds": {segment.name: segment.kind for segment in segments},
        },
    )


def run_generic_evolution(
    hooks: GenericEvolutionHooks,
    *,
    state: dict[str, Any] | None = None,
    config: EvolutionConfig | None = None,
    initial_candidates: list[dict[str, Any]] | None = None,
) -> EvolutionResult:
    """Run the fixed GA/NSGA-II driver over an untyped persistent artifact."""

    cfg = config or EvolutionConfig()
    selection_mode = str(cfg.selection_mode or "auto").strip().lower()
    if selection_mode not in {"auto", "scalar_ga", "moea"}:
        raise ValueError(f"unsupported selection_mode: {cfg.selection_mode}")
    rng = random.Random(cfg.seed)
    state = state or {}

    def checked(value: Any, hook_name: str) -> dict[str, Any]:
        if not isinstance(value, dict):
            raise ValueError(f"generic Workbench hook {hook_name} must return a candidate dict")
        return copy.deepcopy(value)

    population = [
        Candidate(checked(hooks.coerce_repair(copy.deepcopy(candidate), state, rng), "coerce_repair"))
        for candidate in list(initial_candidates or [])[: cfg.population_size]
    ]
    while len(population) < cfg.population_size:
        population.append(Candidate(checked(hooks.initialize(state, rng), "initialize")))

    _evaluate_population(population, hooks.evaluate_decode, None, None, state)
    multi = _selection_is_multi(selection_mode, population)
    if multi:
        population = nsga2_select(population, cfg.population_size)
    else:
        population.sort(key=_scalar_key)
    archive_diagnostics: dict[str, Any] = {}
    archive = _archive(population, [], cfg.archive_limit, diagnostics=archive_diagnostics)
    early_stopper = _ReferenceFreeEarlyStopper(cfg)
    history = [
        _history_row(
            0,
            population,
            multi,
            archive=archive,
            record_metrics=cfg.record_metric_history,
            record_archive=cfg.record_archive_history,
            archive_limit=cfg.history_archive_limit,
            metric_recorder=cfg.history_metric_recorder,
        )
    ]
    early_stopper.update(0, population, archive, multi)
    executed_generations = 0

    for generation in range(1, cfg.generations + 1):
        children: list[Candidate] = []
        while len(children) < cfg.population_size:
            p1 = _tournament(population, rng, cfg.tournament_size, multi)
            p2 = _tournament(population, rng, cfg.tournament_size, multi)
            if rng.random() < cfg.crossover_rate:
                genome = checked(
                    hooks.crossover(copy.deepcopy(p1.genome), copy.deepcopy(p2.genome), state, rng),
                    "crossover",
                )
            else:
                genome = copy.deepcopy(p1.genome)
            genome = checked(hooks.mutate(genome, state, rng), "mutate")
            children.append(Candidate(genome))
        _evaluate_population(children, hooks.evaluate_decode, None, None, state)
        multi = multi or _selection_is_multi(selection_mode, children)
        if multi:
            population = nsga2_select(population + children, cfg.population_size)
        else:
            population = _scalar_select(population + children, cfg.population_size)
        archive = _archive(population, archive, cfg.archive_limit, diagnostics=archive_diagnostics)
        executed_generations = generation
        should_record_history = (cfg.record_metric_history or cfg.record_archive_history) and (
            generation % max(1, int(cfg.history_interval or 1)) == 0 or generation == cfg.generations
        )
        history.append(
            _history_row(
                generation,
                population,
                multi,
                archive=archive,
                record_metrics=should_record_history and cfg.record_metric_history,
                record_archive=should_record_history and cfg.record_archive_history,
                archive_limit=cfg.history_archive_limit,
                metric_recorder=cfg.history_metric_recorder,
            )
        )
        if early_stopper.update(generation, population, archive, multi):
            if not should_record_history and (cfg.record_metric_history or cfg.record_archive_history):
                history[-1] = _history_row(
                    generation,
                    population,
                    multi,
                    archive=archive,
                    record_metrics=bool(cfg.record_metric_history),
                    record_archive=bool(cfg.record_archive_history),
                    archive_limit=cfg.history_archive_limit,
                    metric_recorder=cfg.history_metric_recorder,
                )
            break

    early_stop_metadata = early_stopper.metadata()
    return EvolutionResult(
        best=population[0],
        population=population,
        archive=archive,
        history=history,
        metadata={
            "selection": "nsga2" if multi else "scalar_ga",
            "selection_mode": selection_mode,
            "population_size": cfg.population_size,
            "generations": cfg.generations,
            "executed_generations": executed_generations,
            "early_stopped": bool(early_stop_metadata.get("stopped")),
            "early_stop": early_stop_metadata,
            "record_metric_history": bool(cfg.record_metric_history),
            "record_archive_history": bool(cfg.record_archive_history),
            "history_interval": int(cfg.history_interval),
            "history_archive_limit": int(cfg.history_archive_limit),
            "archive_diagnostics": dict(archive_diagnostics),
            "workbench_interface": "generic_operator_hooks_v1",
        },
    )


def run_exact_enumeration(
    segments: list[SegmentSpec],
    evaluate: EvaluateFn,
    *,
    decode: DecodeFn | None = None,
    repair: RepairFn | None = None,
    data: dict[str, Any] | None = None,
    config: EvolutionConfig | None = None,
    max_candidates: int | None = None,
) -> EvolutionResult:
    """Exhaustively solve small finite search spaces declared by segments.

    This is a generic solver mode for compact discrete models such as subset
    selection, small set cover, and small assignment instances. It does not know
    benchmark families or objective semantics; generated fitness code still
    owns the model semantics, and this function only enumerates chromosome
    primitives.
    """

    if not segments:
        raise ValueError("at least one SegmentSpec is required")
    cfg = config or EvolutionConfig()
    limit = int(max_candidates or cfg.exact_enumeration_limit)
    if limit <= 0:
        raise ValueError("exact enumeration limit must be positive")
    count = exact_search_space_size(segments, limit)
    if count > limit:
        raise ValueError(f"exact search space has {count} candidates, above limit {limit}")
    data = data or {}
    population = [Candidate(genome) for genome in enumerate_exact_genomes(segments, limit)]
    if not population:
        raise ValueError("exact enumeration produced no candidates")
    _evaluate_population(population, evaluate, decode, repair, data)
    selection_mode = str(cfg.selection_mode or "scalar_ga").strip().lower()
    if selection_mode not in {"auto", "scalar_ga", "moea"}:
        raise ValueError(f"unsupported selection_mode: {cfg.selection_mode}")
    multi = _selection_is_multi(selection_mode, population)
    if multi:
        selected = nsga2_select(population, min(cfg.population_size, len(population)))
    else:
        selected = _scalar_select(population, min(cfg.population_size, len(population)))
    archive_diagnostics: dict[str, Any] = {}
    archive = _archive(population, [], cfg.archive_limit, diagnostics=archive_diagnostics)
    return EvolutionResult(
        best=selected[0],
        population=selected,
        archive=archive,
        history=[
            _history_row(
                0,
                selected,
                multi,
                archive=archive,
                record_metrics=cfg.record_metric_history,
                record_archive=cfg.record_archive_history,
                archive_limit=cfg.history_archive_limit,
                metric_recorder=cfg.history_metric_recorder,
            )
        ],
        metadata={
            "selection": "exact_enumeration",
            "selection_mode": selection_mode,
            "population_size": len(selected),
            "generations": 0,
            "record_metric_history": bool(cfg.record_metric_history),
            "record_archive_history": bool(cfg.record_archive_history),
            "history_interval": int(cfg.history_interval),
            "history_archive_limit": int(cfg.history_archive_limit),
            "archive_diagnostics": dict(archive_diagnostics),
            "enumerated_candidates": len(population),
            "search_space_size": count,
            "segment_kinds": {segment.name: segment.kind for segment in segments},
        },
    )


def exact_search_space_size(segments: list[SegmentSpec], limit: int | None = None) -> int:
    total = 1
    cap = limit if limit is not None else math.inf
    for segment in segments:
        total *= _exact_segment_size(segment)
        if total > cap:
            return total
    return total


def enumerate_exact_genomes(segments: list[SegmentSpec], limit: int | None = None) -> Iterable[dict[str, Any]]:
    cap = limit if limit is not None else math.inf
    count = exact_search_space_size(segments, int(cap) if math.isfinite(cap) else None)
    if count > cap:
        raise ValueError(f"exact search space has {count} candidates, above limit {cap}")
    names = [segment.name for segment in segments]
    domains = [_exact_segment_domain(segment) for segment in segments]
    for values in itertools.product(*domains):
        yield {name: copy.deepcopy(value) for name, value in zip(names, values)}


def nsga2_select(candidates: list[Candidate], size: int) -> list[Candidate]:
    selected: list[Candidate] = []
    for rank, front in enumerate(nondominated_fronts(candidates)):
        distances = crowding_distance(front)
        for idx, candidate in enumerate(front):
            candidate.rank = rank
            candidate.crowding_distance = distances[idx]
        ordered = sorted(front, key=lambda c: (c.rank, -c.crowding_distance, _violation_score(c)))
        remaining = size - len(selected)
        if remaining <= 0:
            break
        selected.extend(ordered[:remaining])
    return selected


def nondominated_fronts(candidates: list[Candidate]) -> list[list[Candidate]]:
    n = len(candidates)
    feasible = [bool(candidate.result and candidate.result.feasible) for candidate in candidates]
    violations = [_violation_score(candidate) for candidate in candidates]
    scalars = [_scalar(candidate) for candidate in candidates]
    vectors = [tuple(_objective_vector(candidate)) for candidate in candidates]
    fast = _nondominated_fronts_numpy(candidates, feasible, violations, scalars, vectors)
    if fast is not None:
        return fast
    dominates: list[list[int]] = [[] for _ in range(n)]
    domination_count = [0] * n
    front = []
    for i in range(n):
        for j in range(i + 1, n):
            if _dominates_cached(i, j, feasible, violations, scalars, vectors):
                dominates[i].append(j)
                domination_count[j] += 1
            elif _dominates_cached(j, i, feasible, violations, scalars, vectors):
                dominates[j].append(i)
                domination_count[i] += 1
        if domination_count[i] == 0:
            front.append(i)
    fronts: list[list[Candidate]] = []
    while front:
        fronts.append([candidates[idx] for idx in front])
        next_front: list[int] = []
        for idx in front:
            for dominated_idx in dominates[idx]:
                domination_count[dominated_idx] -= 1
                if domination_count[dominated_idx] == 0:
                    next_front.append(dominated_idx)
        front = next_front
    return fronts


def _nondominated_fronts_numpy(
    candidates: list[Candidate],
    feasible: list[bool],
    violations: list[float],
    scalars: list[float],
    vectors: list[tuple[float, ...]],
) -> list[list[Candidate]] | None:
    if not candidates:
        return []
    dims = {len(vector) for vector in vectors}
    if len(dims) != 1:
        return None
    dim = next(iter(dims))
    if dim <= 1:
        return None
    try:
        import numpy as np
    except Exception:
        return None
    feasible_arr = np.asarray(feasible, dtype=bool)
    violation_arr = np.asarray(violations, dtype=float)
    scalar_arr = np.asarray(scalars, dtype=float)
    vector_arr = np.asarray(vectors, dtype=float)
    feasible_i = feasible_arr[:, None]
    feasible_j = feasible_arr[None, :]
    dominates = feasible_i & ~feasible_j
    both_infeasible = ~feasible_i & ~feasible_j
    dominates |= both_infeasible & (violation_arr[:, None] < violation_arr[None, :])
    both_feasible = feasible_i & feasible_j
    le = np.all(vector_arr[:, None, :] <= vector_arr[None, :, :], axis=2)
    lt = np.any(vector_arr[:, None, :] < vector_arr[None, :, :], axis=2)
    dominates |= both_feasible & le & lt
    scalar_tie_break = both_feasible & ~le & (scalar_arr[:, None] < scalar_arr[None, :])
    dominates |= scalar_tie_break & (dim <= 1)
    np.fill_diagonal(dominates, False)
    domination_count = dominates.sum(axis=0).astype(int).tolist()
    dominate_indices = [np.flatnonzero(row).astype(int).tolist() for row in dominates]
    front = [idx for idx, count in enumerate(domination_count) if count == 0]
    fronts: list[list[Candidate]] = []
    while front:
        fronts.append([candidates[idx] for idx in front])
        next_front: list[int] = []
        for idx in front:
            for dominated_idx in dominate_indices[idx]:
                domination_count[dominated_idx] -= 1
                if domination_count[dominated_idx] == 0:
                    next_front.append(dominated_idx)
        front = next_front
    return fronts


def _dominates_cached(
    i: int,
    j: int,
    feasible: list[bool],
    violations: list[float],
    scalars: list[float],
    vectors: list[tuple[float, ...]],
) -> bool:
    if feasible[i] and not feasible[j]:
        return True
    if feasible[j] and not feasible[i]:
        return False
    if not feasible[i] and not feasible[j]:
        return violations[i] < violations[j]
    av = vectors[i]
    bv = vectors[j]
    if len(av) <= 1 or len(av) != len(bv):
        return scalars[i] < scalars[j]
    return all(x <= y for x, y in zip(av, bv)) and any(x < y for x, y in zip(av, bv))


def crowding_distance(front: list[Candidate]) -> list[float]:
    if not front:
        return []
    if len(front) <= 2:
        return [float("inf")] * len(front)
    vectors = [_objective_vector(candidate) for candidate in front]
    dim = min((len(v) for v in vectors), default=0)
    if dim <= 1:
        return [0.0] * len(front)
    distance = [0.0] * len(front)
    for objective_idx in range(dim):
        order = sorted(range(len(front)), key=lambda idx: vectors[idx][objective_idx])
        distance[order[0]] = float("inf")
        distance[order[-1]] = float("inf")
        low = vectors[order[0]][objective_idx]
        high = vectors[order[-1]][objective_idx]
        scale = max(high - low, 1e-12)
        for pos in range(1, len(order) - 1):
            idx = order[pos]
            if math.isinf(distance[idx]):
                continue
            prev_value = vectors[order[pos - 1]][objective_idx]
            next_value = vectors[order[pos + 1]][objective_idx]
            distance[idx] += (next_value - prev_value) / scale
    return distance


def coerce_fitness_result(value: FitnessResult | dict[str, Any] | float | int, solution: dict[str, Any]) -> FitnessResult:
    if isinstance(value, FitnessResult):
        if not value.solution:
            value.solution = solution
        return value
    if isinstance(value, dict):
        objectives = value.get("objectives")
        if isinstance(objectives, dict):
            objectives = [objectives[key] for key in sorted(objectives)]
        if not isinstance(objectives, list):
            objectives = []
        scalar = value.get("scalar")
        base_scalar = value.get("base_scalar")
        penalty = _finite(value.get("penalty", 0.0))
        if scalar is None:
            scalar = sum(float(item) for item in objectives) if objectives else value.get("value", 0.0)
        violations = value.get("violations")
        if penalty == 0.0 and isinstance(violations, dict) and value.get("feasible") is False:
            penalty = violation_amount(violations)
        return FitnessResult(
            scalar=_finite(scalar),
            objectives=[_finite(item) for item in objectives],
            feasible=bool(value.get("feasible", True)),
            violations=violations if isinstance(violations, dict) else {},
            base_scalar=_finite(base_scalar) if base_scalar is not None else None,
            penalty=penalty,
            solution=value.get("solution") if isinstance(value.get("solution"), dict) else solution,
            diagnostics=value.get("diagnostics") if isinstance(value.get("diagnostics"), dict) else {},
        )
    return FitnessResult(scalar=_finite(value), objectives=[], feasible=True, solution=solution)


def _evaluate_population(
    population: list[Candidate],
    evaluate: EvaluateFn,
    decode: DecodeFn | None,
    repair: RepairFn | None,
    data: dict[str, Any],
) -> None:
    for candidate in population:
        solution = decode(candidate.genome, data) if decode else copy.deepcopy(candidate.genome)
        if repair:
            solution = repair(solution, data)
        candidate.result = coerce_fitness_result(evaluate(solution, data), solution)


def _copy_genome(genome: dict[str, Any], segments: Iterable[SegmentSpec] | None = None) -> dict[str, Any]:
    """Copy a compositional genome without recursively copying large artifacts.

    Genomes produced by the template optimizer are shallow structures built from
    segment primitives: numeric vectors, permutations, choice vectors, and
    demand-to-resource assignment maps. A full ``copy.deepcopy`` is much slower
    in the inner GA/NSGA-II loop and does not add useful isolation for these
    primitives. This helper copies the segment containers and their plain
    Python values while leaving immutable ids/numbers untouched.
    """

    if not isinstance(genome, dict):
        return copy.deepcopy(genome)
    if segments is None:
        return {key: _copy_plain_value(value) for key, value in genome.items()}
    out: dict[str, Any] = {}
    copied = set()
    for segment in segments:
        if segment.name in genome:
            out[segment.name] = _copy_segment_value(genome[segment.name], segment)
            copied.add(segment.name)
    for key, value in genome.items():
        if key not in copied:
            out[key] = _copy_plain_value(value)
    return out


def _copy_segment_value(value: Any, segment: SegmentSpec) -> Any:
    if value is None:
        return None
    if segment.kind in {"real_vector", "int_vector", "binary_vector", "permutation", "choice_vector"}:
        return [_copy_plain_value(item) for item in list(value)]
    if segment.kind in {"assignment", "optional_assignment"}:
        if not isinstance(value, dict):
            return _copy_plain_value(value)
        return {key: _copy_plain_value(item) for key, item in value.items()}
    return _copy_plain_value(value)


def _copy_plain_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, list):
        return [_copy_plain_value(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_copy_plain_value(item) for item in value)
    if isinstance(value, dict):
        return {key: _copy_plain_value(item) for key, item in value.items()}
    return copy.deepcopy(value)


def _random_segment(segment: SegmentSpec, rng: random.Random) -> Any:
    if segment.kind == "real_vector":
        return [_random_real(segment, idx, rng) for idx in range(segment.length)]
    if segment.kind == "int_vector":
        return [_random_int(segment, idx, rng) for idx in range(segment.length)]
    if segment.kind == "binary_vector":
        return [rng.randrange(2) for _ in range(segment.length)]
    if segment.kind == "permutation":
        values = list(segment.values)
        rng.shuffle(values)
        return values
    if segment.kind == "choice_vector":
        return [copy.deepcopy(rng.choice(segment.options)) for _ in range(segment.length)]
    if segment.kind in {"assignment", "optional_assignment"}:
        options = list(segment.resources)
        if segment.allow_none or segment.kind == "optional_assignment":
            options = options + [None]
        return {demand: copy.deepcopy(rng.choice(options)) if options else None for demand in segment.demands}
    raise ValueError(f"unsupported segment kind: {segment.kind}")


def _repair_genome_segments(genome: dict[str, Any], segments: list[SegmentSpec], rng: random.Random) -> dict[str, Any]:
    repaired = _copy_genome(genome, segments)
    segment_by_name = {segment.name: segment for segment in segments}
    for segment in segments:
        if segment.kind not in {"assignment", "optional_assignment"}:
            continue
        value = repaired.get(segment.name)
        if not isinstance(value, dict):
            continue
        value = _repair_assignment_domain(value, segment, rng)
        group_rules = _assignment_group_capacity_rules(segment)
        for rule in _assignment_resource_gate_rules(segment):
            value = _repair_assignment_resource_gate(value, segment, rule, segment_by_name, repaired)
        for rule in group_rules:
            value = _repair_assignment_group_capacity(value, segment, rule, rng)
        for rule in _assignment_resource_capacity_rules(segment):
            value = _repair_assignment_resource_capacity(value, segment, rule, group_rules, rng)
        for rule in _assignment_resource_gate_rules(segment):
            value = _repair_assignment_resource_gate(value, segment, rule, segment_by_name, repaired)
        for rule in group_rules:
            value = _repair_assignment_group_capacity(value, segment, rule, rng)
        repaired[segment.name] = value
    return repaired


def _repair_assignment_domain(assignment: dict[Any, Any], segment: SegmentSpec, rng: random.Random) -> dict[Any, Any]:
    resources = list(segment.resources)
    allowed = set(resources)
    out: dict[Any, Any] = {}
    for demand in segment.demands:
        value = assignment.get(demand, assignment.get(str(demand)))
        if value in allowed:
            out[demand] = copy.deepcopy(value)
        elif (segment.allow_none or segment.kind == "optional_assignment") and value is None:
            out[demand] = None
        elif resources:
            out[demand] = copy.deepcopy(rng.choice(resources))
        else:
            out[demand] = None
    return out


def _assignment_group_capacity_rules(segment: SegmentSpec) -> list[dict[str, Any]]:
    metadata = segment.metadata if isinstance(segment.metadata, dict) else {}
    raw = (
        metadata.get("exclusive_resource_per_group")
        or metadata.get("assignment_group_capacity")
        or metadata.get("resource_group_capacity")
    )
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    rules = []
    for item in items:
        if not isinstance(item, dict):
            continue
        demand_to_group = item.get("demand_to_group") or item.get("groups")
        if not isinstance(demand_to_group, dict):
            continue
        try:
            capacity = int(item.get("capacity", item.get("max_per_group", 1)) or 1)
        except (TypeError, ValueError):
            capacity = 1
        rules.append({"demand_to_group": {str(k): v for k, v in demand_to_group.items()}, "capacity": max(1, capacity)})
    return rules


def _assignment_resource_gate_rules(segment: SegmentSpec) -> list[dict[str, Any]]:
    metadata = segment.metadata if isinstance(segment.metadata, dict) else {}
    if isinstance(metadata.get("metadata"), dict):
        metadata = {**metadata["metadata"], **{key: value for key, value in metadata.items() if key != "metadata"}}
    raw = (
        metadata.get("resource_open_gate")
        or metadata.get("open_resource_gate")
        or metadata.get("resource_gate")
        or metadata.get("resource_activation")
    )
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    rules = []
    for item in items:
        if isinstance(item, str):
            item = {"segment": item}
        if not isinstance(item, dict):
            continue
        gate_segment = (
            item.get("segment")
            or item.get("gate_segment")
            or item.get("open_segment")
            or item.get("activation_segment")
        )
        if not gate_segment:
            continue
        resources = item.get("resources") or item.get("resource_order") or item.get("resource_ids") or segment.resources
        if not isinstance(resources, list) or not resources:
            continue
        rules.append(
            {
                "segment": str(gate_segment),
                "resources": list(resources),
                "open_value": item.get("open_value", item.get("active_value", 1)),
            }
        )
    return rules


def _repair_assignment_resource_gate(
    assignment: dict[Any, Any],
    segment: SegmentSpec,
    rule: dict[str, Any],
    segment_by_name: dict[str, SegmentSpec],
    genome: dict[str, Any],
) -> dict[Any, Any]:
    gate_name = str(rule.get("segment") or "")
    gate_segment = segment_by_name.get(gate_name)
    if gate_segment is None:
        return dict(assignment)
    if gate_segment.kind not in {"binary_vector", "int_vector", "choice_vector"}:
        return dict(assignment)
    gate_value = genome.get(gate_name)
    if not isinstance(gate_value, list):
        gate_value = _closed_gate_vector(gate_segment)
    else:
        gate_value = list(gate_value[: gate_segment.length])
        if len(gate_value) < gate_segment.length:
            gate_value.extend(_closed_gate_vector(gate_segment)[len(gate_value) :])
    open_value = _coerce_gate_open_value(rule.get("open_value", 1), gate_segment)
    resource_index = _resource_index(rule.get("resources") or [])
    for resource in assignment.values():
        if resource is None:
            continue
        idx = resource_index.get(resource, resource_index.get(str(resource)))
        if idx is None or idx >= gate_segment.length:
            continue
        gate_value[idx] = copy.deepcopy(open_value)
    genome[gate_name] = gate_value
    return dict(assignment)


def _closed_gate_vector(segment: SegmentSpec) -> list[Any]:
    if segment.kind == "choice_vector" and segment.options:
        return [copy.deepcopy(segment.options[0]) for _ in range(segment.length)]
    return [0 for _ in range(segment.length)]


def _coerce_gate_open_value(value: Any, segment: SegmentSpec) -> Any:
    if segment.kind == "binary_vector":
        return 1 if bool(value) else 0
    if segment.kind == "int_vector":
        try:
            return int(value)
        except (TypeError, ValueError):
            return 1
    if segment.kind == "choice_vector":
        if value in segment.options:
            return copy.deepcopy(value)
        if True in segment.options:
            return True
        if 1 in segment.options:
            return 1
        if "open" in segment.options:
            return "open"
        if "active" in segment.options:
            return "active"
        return copy.deepcopy(segment.options[-1]) if segment.options else value
    return value


def _resource_index(resources: list[Any]) -> dict[Any, int]:
    out: dict[Any, int] = {}
    for idx, resource in enumerate(resources):
        out[resource] = idx
        out[str(resource)] = idx
    return out


def _assignment_resource_capacity_rules(segment: SegmentSpec) -> list[dict[str, Any]]:
    metadata = segment.metadata if isinstance(segment.metadata, dict) else {}
    raw = (
        metadata.get("resource_total_capacity")
        or metadata.get("assignment_resource_capacity")
        or metadata.get("resource_capacity")
    )
    if raw is None:
        return []
    items = raw if isinstance(raw, list) else [raw]
    rules = []
    for item in items:
        if isinstance(item, dict) and any(key in item for key in ("resource_capacity", "capacities", "capacity_by_resource")):
            capacities = item.get("resource_capacity") or item.get("capacities") or item.get("capacity_by_resource")
        else:
            capacities = item
        if not isinstance(capacities, dict):
            continue
        parsed: dict[str, int] = {}
        for resource, capacity in capacities.items():
            try:
                parsed[str(resource)] = max(0, int(float(capacity)))
            except (TypeError, ValueError):
                continue
        if parsed:
            rules.append({"resource_capacity": parsed})
    return rules


def _repair_assignment_group_capacity(
    assignment: dict[Any, Any],
    segment: SegmentSpec,
    rule: dict[str, Any],
    rng: random.Random,
) -> dict[Any, Any]:
    demand_to_group = rule.get("demand_to_group") if isinstance(rule.get("demand_to_group"), dict) else {}
    capacity = int(rule.get("capacity") or 1)
    resources = list(segment.resources)
    if not resources or capacity <= 0:
        return dict(assignment)
    out = dict(assignment)
    group_resource_demands: dict[Any, dict[Any, list[Any]]] = {}
    for demand in segment.demands:
        group = demand_to_group.get(str(demand), demand_to_group.get(demand))
        if group is None:
            continue
        resource = out.get(demand)
        if resource is None:
            continue
        group_resource_demands.setdefault(group, {}).setdefault(resource, []).append(demand)
    for group, by_resource in group_resource_demands.items():
        counts = {resource: len(by_resource.get(resource, [])) for resource in resources}
        overflow: list[Any] = []
        for resource, demands in by_resource.items():
            if len(demands) <= capacity:
                continue
            keep = list(demands[:capacity])
            extras = list(demands[capacity:])
            by_resource[resource] = keep
            counts[resource] = capacity
            overflow.extend(extras)
        if not overflow:
            continue
        rng.shuffle(overflow)
        for demand in overflow:
            available = [resource for resource in resources if counts.get(resource, 0) < capacity]
            if not available:
                break
            resource = rng.choice(available)
            out[demand] = copy.deepcopy(resource)
            counts[resource] = counts.get(resource, 0) + 1
    return out


def _repair_assignment_resource_capacity(
    assignment: dict[Any, Any],
    segment: SegmentSpec,
    rule: dict[str, Any],
    group_rules: list[dict[str, Any]],
    rng: random.Random,
) -> dict[Any, Any]:
    capacities = rule.get("resource_capacity") if isinstance(rule.get("resource_capacity"), dict) else {}
    if not capacities:
        return dict(assignment)
    resources = [resource for resource in segment.resources if str(resource) in capacities and capacities[str(resource)] > 0]
    if not resources:
        return dict(assignment)
    out = dict(assignment)
    by_resource: dict[Any, list[Any]] = {resource: [] for resource in resources}
    for demand in segment.demands:
        resource = out.get(demand)
        if resource in by_resource:
            by_resource[resource].append(demand)
    overflow: list[Any] = []
    counts: dict[Any, int] = {}
    for resource, demands in by_resource.items():
        capacity = capacities[str(resource)]
        counts[resource] = min(len(demands), capacity)
        if len(demands) > capacity:
            keep = list(demands[:capacity])
            overflow.extend(demands[capacity:])
            by_resource[resource] = keep
    if not overflow:
        return out
    rng.shuffle(overflow)
    for demand in overflow:
        available = [
            resource
            for resource in resources
            if counts.get(resource, 0) < capacities[str(resource)]
            and _group_capacity_allows(out, demand, resource, group_rules)
        ]
        if not available:
            if segment.allow_none:
                out[demand] = None
            continue
        resource = rng.choice(available)
        out[demand] = copy.deepcopy(resource)
        counts[resource] = counts.get(resource, 0) + 1
    return out


def _group_capacity_allows(
    assignment: dict[Any, Any],
    demand: Any,
    resource: Any,
    group_rules: list[dict[str, Any]],
) -> bool:
    for rule in group_rules:
        demand_to_group = rule.get("demand_to_group") if isinstance(rule.get("demand_to_group"), dict) else {}
        group = demand_to_group.get(str(demand), demand_to_group.get(demand))
        if group is None:
            continue
        capacity = int(rule.get("capacity") or 1)
        used = 0
        for other_demand, other_resource in assignment.items():
            if other_demand == demand or other_resource != resource:
                continue
            other_group = demand_to_group.get(str(other_demand), demand_to_group.get(other_demand))
            if other_group == group:
                used += 1
        if used >= capacity:
            return False
    return True


def _structured_seed_genomes(segments: list[SegmentSpec], limit: int) -> list[dict[str, Any]]:
    """Generic low-discrepancy seeds for reusable optimization templates.

    These seeds are problem agnostic: they expose bounds, centers, order
    reversals, and round-robin assignments before random search starts. They
    reduce early collapse without encoding any benchmark semantics.
    """

    if limit <= 0:
        return []
    base = {segment.name: _seed_segment(segment, "middle", 0) for segment in segments}
    seeds = [copy.deepcopy(base)]
    for mode in ["lower", "upper", "reverse"]:
        seeds.append({segment.name: _seed_segment(segment, mode, 0) for segment in segments})
    for fraction_index in range(6):
        seeds.append(
            {
                segment.name: _seed_segment(segment, "quantile", fraction_index)
                for segment in segments
            }
        )
    for segment in segments:
        width = max(1, _segment_length(segment))
        for idx in range(min(width, max(1, limit // max(1, len(segments))))):
            genome = copy.deepcopy(base)
            genome[segment.name] = _seed_segment(segment, "sweep", idx)
            seeds.append(genome)
            if len(seeds) >= limit:
                return _unique_seed_genomes(seeds, limit)
    return _unique_seed_genomes(seeds, limit)


def _seed_segment(segment: SegmentSpec, mode: str, idx: int) -> Any:
    length = _segment_length(segment)
    if segment.kind == "real_vector":
        lows = [_bound(segment.lower, i) for i in range(segment.length)]
        highs = [_bound(segment.upper, i) for i in range(segment.length)]
        fractions = [0.1, 0.25, 0.5, 0.6, 0.65, 0.75, 0.9]
        if mode == "lower":
            return lows
        if mode == "upper":
            return highs
        if mode == "quantile":
            fraction = fractions[idx % len(fractions)]
            return [lo + fraction * (hi - lo) for lo, hi in zip(lows, highs)]
        if mode == "sweep":
            out = list(lows)
            pos = (idx // len(fractions)) % max(1, segment.length)
            fraction = fractions[idx % len(fractions)]
            out[pos] = lows[pos] + min(1.0, fraction) * (highs[pos] - lows[pos])
            return out
        return [(lo + hi) / 2.0 for lo, hi in zip(lows, highs)]
    if segment.kind == "int_vector":
        lows = [math.ceil(_bound(segment.lower, i)) for i in range(segment.length)]
        highs = [math.floor(_bound(segment.upper, i)) for i in range(segment.length)]
        levels = 6
        if mode == "lower":
            return lows
        if mode == "upper":
            return highs
        if mode == "quantile":
            fraction = idx / max(1, levels - 1)
            return [int(round(lo + fraction * (hi - lo))) for lo, hi in zip(lows, highs)]
        if mode == "sweep":
            out = list(lows)
            pos = (idx // levels) % max(1, segment.length)
            span = max(1, highs[pos] - lows[pos] + 1)
            out[pos] = lows[pos] + ((idx % levels) % span)
            return out
        return [(lo + hi) // 2 for lo, hi in zip(lows, highs)]
    if segment.kind == "binary_vector":
        if mode == "upper":
            return [1] * segment.length
        if mode == "sweep":
            out = [0] * segment.length
            out[idx % max(1, segment.length)] = 1
            return out
        return [0] * segment.length
    if segment.kind == "permutation":
        values = list(segment.values)
        if mode == "reverse":
            return list(reversed(values))
        if mode == "sweep" and values:
            shift = idx % len(values)
            return values[shift:] + values[:shift]
        return values
    if segment.kind == "choice_vector":
        options = list(segment.options)
        if not options:
            return []
        if mode == "upper":
            return [copy.deepcopy(options[-1])] * segment.length
        if mode == "sweep":
            return [copy.deepcopy(options[(i + idx) % len(options)]) for i in range(segment.length)]
        return [copy.deepcopy(options[0])] * segment.length
    if segment.kind in {"assignment", "optional_assignment"}:
        options = list(segment.resources)
        if segment.kind == "optional_assignment" or segment.allow_none:
            options = options + [None]
        if not options:
            return {demand: None for demand in segment.demands}
        offset = idx if mode == "sweep" else 0 if mode in {"lower", "middle"} else len(options) - 1
        return {demand: copy.deepcopy(options[(i + offset) % len(options)]) for i, demand in enumerate(segment.demands)}
    raise ValueError(f"unsupported segment kind: {segment.kind}")


def _unique_seed_genomes(seeds: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for seed in seeds:
        key = repr(seed)
        if key in seen:
            continue
        seen.add(key)
        out.append(seed)
        if len(out) >= limit:
            break
    return out


def _crossover_segment(segment: SegmentSpec, a: Any, b: Any, rng: random.Random, eta_c: float) -> Any:
    if a is None:
        return copy.deepcopy(b)
    if b is None:
        return copy.deepcopy(a)
    if segment.kind == "real_vector":
        return _sbx_vector([float(x) for x in a], [float(x) for x in b], segment, rng, eta_c)
    if segment.kind in {"int_vector", "binary_vector", "choice_vector"}:
        return [copy.deepcopy(x if rng.random() < 0.5 else y) for x, y in zip(list(a), list(b))]
    if segment.kind == "permutation":
        return _order_crossover(list(a), list(b), rng)
    if segment.kind in {"assignment", "optional_assignment"}:
        return {
            demand: copy.deepcopy(a.get(demand) if rng.random() < 0.5 else b.get(demand))
            for demand in segment.demands
        }
    raise ValueError(f"unsupported segment kind: {segment.kind}")


def _mutate_segment(segment: SegmentSpec, value: Any, rng: random.Random, rate: float, eta_m: float) -> Any:
    if value is None:
        return _random_segment(segment, rng)
    if segment.kind == "real_vector":
        return [_polynomial_mutation(float(x), _bound(segment.lower, i), _bound(segment.upper, i), rng, rate, eta_m) for i, x in enumerate(value)]
    if segment.kind == "int_vector":
        return [_random_int(segment, i, rng) if rng.random() < rate else int(x) for i, x in enumerate(value)]
    if segment.kind == "binary_vector":
        return [1 - int(x) if rng.random() < rate else int(x) for x in value]
    if segment.kind == "choice_vector":
        return [copy.deepcopy(rng.choice(segment.options)) if rng.random() < rate else copy.deepcopy(x) for x in value]
    if segment.kind == "permutation":
        items = list(value)
        if len(items) >= 2 and rng.random() < max(rate * len(items), rate):
            i, j = rng.sample(range(len(items)), 2)
            items[i], items[j] = items[j], items[i]
        return items
    if segment.kind in {"assignment", "optional_assignment"}:
        options = list(segment.resources)
        if segment.allow_none or segment.kind == "optional_assignment":
            options = options + [None]
        out = dict(value)
        for demand in segment.demands:
            if rng.random() < rate:
                out[demand] = copy.deepcopy(rng.choice(options)) if options else None
        return out
    raise ValueError(f"unsupported segment kind: {segment.kind}")


def _sbx_vector(a: list[float], b: list[float], segment: SegmentSpec, rng: random.Random, eta_c: float) -> list[float]:
    child = []
    for idx, (x, y) in enumerate(zip(a, b)):
        if rng.random() > 0.5:
            child.append(x)
            continue
        u = rng.random()
        beta = (2.0 * u) ** (1.0 / (eta_c + 1.0)) if u <= 0.5 else (1.0 / (2.0 * (1.0 - u))) ** (1.0 / (eta_c + 1.0))
        value = 0.5 * ((1.0 + beta) * x + (1.0 - beta) * y)
        child.append(_clip(value, _bound(segment.lower, idx), _bound(segment.upper, idx)))
    return child


def _polynomial_mutation(value: float, lower: float, upper: float, rng: random.Random, rate: float, eta_m: float) -> float:
    if rng.random() >= rate or upper <= lower:
        return _clip(value, lower, upper)
    u = rng.random()
    delta = (2.0 * u) ** (1.0 / (eta_m + 1.0)) - 1.0 if u < 0.5 else 1.0 - (2.0 * (1.0 - u)) ** (1.0 / (eta_m + 1.0))
    return _clip(value + delta * (upper - lower), lower, upper)


def _order_crossover(parent_a: list[Any], parent_b: list[Any], rng: random.Random) -> list[Any]:
    n = len(parent_a)
    if n <= 2:
        return list(parent_a)
    start, end = sorted(rng.sample(range(n), 2))
    child = [None] * n
    child[start : end + 1] = parent_a[start : end + 1]
    fill = [item for item in parent_b if item not in child]
    cursor = 0
    for idx in list(range(end + 1, n)) + list(range(0, start)):
        child[idx] = fill[cursor]
        cursor += 1
    return child


def _scalar_select(candidates: list[Candidate], size: int) -> list[Candidate]:
    return sorted(candidates, key=_scalar_key)[:size]


def _archive(
    population: list[Candidate],
    prior: list[Candidate],
    limit: int,
    *,
    diagnostics: dict[str, Any] | None = None,
) -> list[Candidate]:
    combined = prior + population
    if _is_multi_objective(combined):
        feasible = [candidate for candidate in combined if candidate.result and candidate.result.feasible]
        pool = feasible or combined
        unique = _unique_objective_candidates(pool)
        fronts = nondominated_fronts(unique)
        nondominated = fronts[0] if fronts else []
        selected = nsga2_select(nondominated, min(limit, len(nondominated)))
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update(
                {
                    "combined_candidates": len(combined),
                    "feasible_candidates": len(feasible),
                    "unique_objective_vectors": len(unique),
                    "nondominated_before_truncation": len(nondominated),
                    "archive_size": len(selected),
                    "archive_limit": int(limit),
                    "cap_active": len(nondominated) > int(limit),
                }
            )
    else:
        selected = _scalar_select(combined, min(limit, len(combined)))
        if diagnostics is not None:
            diagnostics.clear()
            diagnostics.update(
                {
                    "combined_candidates": len(combined),
                    "archive_size": len(selected),
                    "archive_limit": int(limit),
                    "cap_active": len(combined) > int(limit),
                }
            )
    return [_snapshot_candidate(candidate) for candidate in selected]


def _unique_objective_candidates(candidates: list[Candidate]) -> list[Candidate]:
    """Keep one representative per exact objective vector in a Pareto archive.

    Population selection may retain duplicate genotypes, but the external archive
    represents trade-off points.  Deduplicating before nondominance filtering
    prevents the archive cap from being filled by identical objective vectors.
    """
    unique: list[Candidate] = []
    seen: set[tuple[float, ...]] = set()
    for candidate in candidates:
        vector = tuple(float(value) for value in _objective_vector(candidate))
        if not vector or vector in seen:
            continue
        seen.add(vector)
        unique.append(candidate)
    return unique


def _snapshot_candidate(candidate: Candidate) -> Candidate:
    result = candidate.result
    result_copy = None
    if result is not None:
        result_copy = FitnessResult(
            scalar=result.scalar,
            objectives=list(result.objectives),
            feasible=result.feasible,
            violations=dict(result.violations),
            base_scalar=result.base_scalar,
            penalty=result.penalty,
            solution=result.solution,
            diagnostics=result.diagnostics,
        )
    return Candidate(
        genome=_copy_genome(candidate.genome),
        result=result_copy,
        rank=candidate.rank,
        crowding_distance=candidate.crowding_distance,
    )


def _tournament(population: list[Candidate], rng: random.Random, size: int, multi: bool) -> Candidate:
    sample = rng.sample(population, min(size, len(population)))
    if multi:
        return min(sample, key=lambda c: (c.rank, -c.crowding_distance, _violation_score(c), _scalar(c)))
    return min(sample, key=_scalar_key)


def _history_row(
    generation: int,
    population: list[Candidate],
    multi: bool,
    *,
    archive: list[Candidate] | None = None,
    record_metrics: bool = False,
    record_archive: bool = False,
    archive_limit: int = 200,
    metric_recorder: Callable[[int, list[Candidate], list[Candidate], bool], dict[str, Any] | None] | None = None,
) -> dict[str, Any]:
    feasible = [c for c in population if c.result and c.result.feasible]
    front_size = 0
    if multi and population:
        ranked_front = [candidate for candidate in population if candidate.rank == 0]
        front_size = len(ranked_front) if ranked_front else len(nondominated_fronts(population)[0])
    row = {
        "generation": generation,
        "feasible": len(feasible),
        "population": len(population),
        "best_scalar": _scalar(population[0]) if population else float("inf"),
        "front_size": front_size,
    }
    source = list(archive or population)
    if record_metrics and metric_recorder is not None:
        extra = metric_recorder(generation, population, source, multi)
        if isinstance(extra, dict):
            row.update(extra)
    if record_archive:
        row["candidate_archive"] = [_history_candidate_record(candidate) for candidate in source[: max(0, int(archive_limit))]]
        row["archive_count"] = len(source)
        row["archive_record_limit"] = int(archive_limit)
    return row


def _history_candidate_record(candidate: Candidate) -> dict[str, Any]:
    result = candidate.result
    if result is None:
        return {"rank": candidate.rank, "solution": {}, "workbench_objectives": [], "workbench_scalar": None, "workbench_feasible": False}
    return {
        "rank": candidate.rank,
        "solution": copy.deepcopy(result.solution or {}),
        "workbench_objectives": list(result.objectives or []),
        "workbench_scalar": result.scalar,
        "workbench_feasible": bool(result.feasible),
    }


def _is_multi_objective(candidates: list[Candidate]) -> bool:
    return any(len(_objective_vector(candidate)) > 1 for candidate in candidates)


def _selection_is_multi(selection_mode: str, candidates: list[Candidate]) -> bool:
    if selection_mode == "moea":
        return True
    if selection_mode == "scalar_ga":
        return False
    return _is_multi_objective(candidates)


def _dominates(a: Candidate, b: Candidate) -> bool:
    if not (a.result and b.result):
        return False
    if a.result.feasible and not b.result.feasible:
        return True
    if b.result.feasible and not a.result.feasible:
        return False
    if not a.result.feasible and not b.result.feasible:
        return _violation_score(a) < _violation_score(b)
    av = _objective_vector(a)
    bv = _objective_vector(b)
    if len(av) <= 1 or len(av) != len(bv):
        return _scalar(a) < _scalar(b)
    return all(x <= y for x, y in zip(av, bv)) and any(x < y for x, y in zip(av, bv))


def _scalar_key(candidate: Candidate) -> tuple[float, float]:
    return (_violation_score(candidate), _scalar(candidate))


def _scalar(candidate: Candidate) -> float:
    if not candidate.result:
        return float("inf")
    return _finite(candidate.result.scalar)


def _objective_vector(candidate: Candidate) -> list[float]:
    if not candidate.result:
        return []
    return [_finite(value) for value in candidate.result.objectives]


def _violation_score(candidate: Candidate) -> float:
    result = candidate.result
    if result is None:
        return float("inf")
    if result.feasible:
        return 0.0
    return float(result.penalty) if result.penalty > 0 else violation_amount(result.violations) or 1.0


def violation_amount(violations: dict[str, Any] | list[Any] | int | float | bool | str | None) -> float:
    """Convert structured constraint violations into a penalty magnitude.

    Generated fitness code can return rich violations such as
    ``{"capacity": {"excess": 3}, "missing": ["d1"]}``; the optimizer uses this
    numeric amount to rank infeasible candidates without hard-coding any problem.
    """

    return _nested_violation_score(violations)


def _nested_violation_score(value: Any) -> float:
    if isinstance(value, dict):
        return sum(_nested_violation_score(item) for item in value.values()) or float(len(value))
    if isinstance(value, list):
        return sum(_nested_violation_score(item) for item in value) or float(len(value))
    if isinstance(value, (int, float)):
        return abs(float(value))
    return 1.0 if value else 0.0


def _random_real(segment: SegmentSpec, idx: int, rng: random.Random) -> float:
    low = float(_bound(segment.lower, idx))
    high = float(_bound(segment.upper, idx))
    return rng.uniform(low, high)


def _random_int(segment: SegmentSpec, idx: int, rng: random.Random) -> int:
    low = math.ceil(float(_bound(segment.lower, idx)))
    high = math.floor(float(_bound(segment.upper, idx)))
    return rng.randint(low, high)


def _bound(value: float | int | list[float | int], idx: int) -> float:
    if isinstance(value, list):
        return float(value[min(idx, len(value) - 1)])
    return float(value)


def _segment_length(segment: SegmentSpec) -> int:
    if segment.kind == "permutation":
        return len(segment.values)
    if segment.kind in {"assignment", "optional_assignment"}:
        return len(segment.demands)
    return segment.length


def _exact_segment_size(segment: SegmentSpec) -> int:
    if segment.kind == "real_vector":
        raise ValueError(f"real_vector segment {segment.name} is continuous and cannot be exactly enumerated")
    if segment.kind == "int_vector":
        size = 1
        for idx in range(segment.length):
            low = math.ceil(_bound(segment.lower, idx))
            high = math.floor(_bound(segment.upper, idx))
            if high < low:
                raise ValueError(f"int_vector segment {segment.name} has invalid bounds at index {idx}")
            size *= high - low + 1
        return size
    if segment.kind == "binary_vector":
        return 2 ** segment.length
    if segment.kind == "permutation":
        return math.factorial(len(segment.values))
    if segment.kind == "choice_vector":
        return len(segment.options) ** segment.length
    if segment.kind in {"assignment", "optional_assignment"}:
        option_count = len(segment.resources) + (1 if segment.kind == "optional_assignment" or segment.allow_none else 0)
        if option_count <= 0:
            raise ValueError(f"{segment.kind} segment {segment.name} has no options to enumerate")
        return option_count ** len(segment.demands)
    raise ValueError(f"unsupported segment kind: {segment.kind}")


def _exact_segment_domain(segment: SegmentSpec) -> list[Any]:
    if segment.kind == "real_vector":
        raise ValueError(f"real_vector segment {segment.name} is continuous and cannot be exactly enumerated")
    if segment.kind == "int_vector":
        ranges = []
        for idx in range(segment.length):
            low = math.ceil(_bound(segment.lower, idx))
            high = math.floor(_bound(segment.upper, idx))
            if high < low:
                raise ValueError(f"int_vector segment {segment.name} has invalid bounds at index {idx}")
            ranges.append(range(low, high + 1))
        return [list(values) for values in itertools.product(*ranges)]
    if segment.kind == "binary_vector":
        return [list(values) for values in itertools.product([0, 1], repeat=segment.length)]
    if segment.kind == "permutation":
        return [list(values) for values in itertools.permutations(segment.values)]
    if segment.kind == "choice_vector":
        return [list(values) for values in itertools.product(segment.options, repeat=segment.length)]
    if segment.kind in {"assignment", "optional_assignment"}:
        options = list(segment.resources)
        if segment.kind == "optional_assignment" or segment.allow_none:
            options.append(None)
        if not options:
            raise ValueError(f"{segment.kind} segment {segment.name} has no options to enumerate")
        return [
            {demand: value for demand, value in zip(segment.demands, values)}
            for values in itertools.product(options, repeat=len(segment.demands))
        ]
    raise ValueError(f"unsupported segment kind: {segment.kind}")


def _clip(value: float, lower: float, upper: float) -> float:
    return min(max(value, lower), upper)


def _finite(value: Any) -> float:
    try:
        output = float(value)
    except Exception:
        return float("inf")
    return output if math.isfinite(output) else float("inf")
