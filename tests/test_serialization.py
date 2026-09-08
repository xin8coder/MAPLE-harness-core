from __future__ import annotations

from liveopt_dsh.serialization import evolution_from_record, evolution_to_record
from evo2.core.template_optimizer import Candidate, EvolutionResult, FitnessResult


def test_evolution_result_round_trip_preserves_search_state():
    fitness = FitnessResult(
        scalar=-3.0,
        objectives=[-3.0, 2.0],
        feasible=True,
        solution={"selected": ["A"]},
    )
    candidate = Candidate(
        genome={"choice": [1, 0]}, result=fitness, rank=0, crowding_distance=float("inf")
    )
    result = EvolutionResult(
        best=candidate,
        population=[candidate],
        archive=[candidate],
        history=[{"generation": 1, "hv": 0.5}],
        metadata={"selection": "nsga2"},
    )
    restored = evolution_from_record(evolution_to_record(result))
    assert restored.best.genome == candidate.genome
    assert restored.best.result.solution == {"selected": ["A"]}
    assert restored.population[0].result.objectives == [-3.0, 2.0]
    assert restored.archive[0].crowding_distance == float("inf")
    assert restored.history == result.history

