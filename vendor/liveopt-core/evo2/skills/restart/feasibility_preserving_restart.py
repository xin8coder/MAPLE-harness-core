from __future__ import annotations

from evo2.skills.base import Skill, SkillContext, SkillResult
from evo2.skills.restart._utils import operator_memory, repair_individual, solution_to_individual, universal_decoder


class FeasibilityPreservingRestartSkill(Skill):
    """Generic restart skill for online optimization under hard constraints.

    The skill does not encode benchmark-specific logic. It preserves the
    previous solution as an explicit seed, repairs it with the available domain
    decoder when one exists, and produces small local variants for downstream
    search. This is useful when an update tightens constraints, changes resource
    availability, or reduces a movement/change budget.
    """

    skill_id = "feasibility_preserving_restart_v1"
    skill_type = "restart"
    description = "Anchor the previous solution, repair hard-constraint violations, then generate local variants."
    suitable_change_scale = "constraint-focused small-to-medium"
    handles = ["resource unavailability", "capacity tightening", "deadline or SLA tightening", "movement budget tightening", "new hard constraints"]
    limitations = ["requires a previous solution", "less exploratory than full restart for global reshuffling"]
    planner_tags = ["repair", "constraint_change", "feasibility_first", "memory_seeded"]

    def applicable(self, context: SkillContext) -> bool:
        return context.previous_solution is not None

    def run(self, context: SkillContext) -> SkillResult:
        previous = context.previous_solution
        population = [solution_to_individual(previous, "previous_feasible_anchor")]
        repaired = repair_individual(solution_to_individual(previous, "constraint_repair"), context)
        population.append(repaired)

        n = int(context.budget.get("feasibility_variants", context.budget.get("warm_variants", 8)))
        decoder = universal_decoder(context)
        for idx in range(n):
            mutated = decoder.mutate_solution(repaired.solution, operator_memory(context))
            population.append(solution_to_individual(mutated, f"feasibility_variant_{idx}"))

        return SkillResult(
            True,
            population,
            {
                "restart": self.skill_id,
                "source": "previous_solution_plus_constraint_repair",
                "count": len(population),
                "policy": "preserve feasibility first, then optimize",
            },
        )
