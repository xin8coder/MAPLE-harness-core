from __future__ import annotations

import copy
import uuid

from evo2.core.population import Individual, Population
from evo2.core.solution import Solution
from evo2.core.universal_codec import UniversalDecoder


def solution_to_individual(solution: Solution, prefix: str) -> Individual:
    sol = copy.deepcopy(solution)
    sol.solution_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
    return Individual(individual_id=f"ind_{sol.solution_id}", solution=sol, metadata={"source": prefix})


def ensure_individual(obj, prefix: str) -> Individual:
    if isinstance(obj, Individual):
        ind = copy.deepcopy(obj)
        ind.individual_id = f"{prefix}_{uuid.uuid4().hex[:8]}"
        ind.solution.solution_id = f"sol_{ind.individual_id}"
        ind.metadata["source"] = prefix
        return ind
    return solution_to_individual(obj, prefix)


def repair_individual(ind: Individual, context) -> Individual:
    repaired = copy.deepcopy(ind)
    decoder = UniversalDecoder.from_context(context)
    repaired.solution = decoder.repair_solution(repaired.solution, _operator_memory(context))
    return repaired


def as_population(individuals, population_id="restart_pop") -> Population:
    return Population(population_id=population_id, individuals=list(individuals), generation=0)


def universal_decoder(context) -> UniversalDecoder:
    return UniversalDecoder.from_context(context)


def operator_memory(context) -> dict:
    return _operator_memory(context)


def _operator_memory(context) -> dict:
    memory = dict(getattr(context, "memory", {}) or {})
    memory.pop("universal_artifact", None)
    memory["natural_language_update"] = getattr(context, "natural_language_update", None)
    return memory
