from __future__ import annotations

from dataclasses import dataclass


@dataclass
class DynamicUpdateMetrics:
    update_success: bool
    feasible: bool
    objective_value: float
    objective_gap: float | None
    disruption_distance: float
    latency_seconds: float
    token_cost: int
    solver_calls: int
    restart_skill_ids: list[str]
    population_reuse_ratio: float
    patch_token_saving: float | None
    time_to_first_feasible: float | None
    diversity_before: float | None
    diversity_after: float | None
