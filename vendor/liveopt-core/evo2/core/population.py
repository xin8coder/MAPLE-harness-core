from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from evo2.core.solution import Solution


@dataclass
class Individual:
    individual_id: str
    solution: Solution
    fitness: float | None = None
    feasible: bool = False
    diversity_signature: str | None = None
    robustness_score: float | None = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Population:
    population_id: str
    individuals: List[Individual]
    generation: int = 0
    metadata: Dict[str, object] = field(default_factory=dict)

    def elites(self, k: int) -> List[Individual]:
        feasible = [i for i in self.individuals if i.feasible]
        pool = feasible if feasible else list(self.individuals)
        return sorted(pool, key=lambda x: x.fitness if x.fitness is not None else float("inf"))[:k]

    def diverse_representatives(self, k: int) -> List[Individual]:
        if k <= 0:
            return []
        seen: set[str] = set()
        reps: List[Individual] = []
        for ind in self.individuals:
            sig = ind.diversity_signature or ind.individual_id
            if sig not in seen:
                seen.add(sig)
                reps.append(ind)
            if len(reps) >= k:
                break
        return reps
