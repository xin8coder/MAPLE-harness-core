from __future__ import annotations

from evo2.skills.base import Skill, SkillContext, SkillResult
from evo2.skills.restart._utils import operator_memory, repair_individual, solution_to_individual, universal_decoder


class WarmRestartSkill(Skill):
    skill_id = "warm_restart_v1"
    skill_type = "restart"
    description = "Seed search from the previous Pareto/front population for multi-objective runs, or the previous best solution plus local variants for scalar runs."
    suitable_change_scale = "small"
    handles = ["minor objective weight changes", "small demand changes", "local timing changes", "stability-preserving updates", "Pareto-front reuse for multi-objective updates"]
    limitations = ["not ideal when many constraints become infeasible", "not ideal for large structural changes"]
    planner_tags = ["previous_best", "low_disruption", "memory_seeded"]

    def applicable(self, context: SkillContext) -> bool:
        return context.previous_solution is not None

    def run(self, context: SkillContext) -> SkillResult:
        previous = context.previous_solution
        base = repair_individual(solution_to_individual(previous, "warm_repair"), context)
        population = [base]
        n = int(context.budget.get("warm_variants", 10))
        decoder = universal_decoder(context)
        for idx in range(n):
            mutated = decoder.mutate_solution(base.solution, operator_memory(context))
            population.append(solution_to_individual(mutated, f"warm_variant_{idx}"))
        return SkillResult(True, population, {"restart": self.skill_id, "source": "previous_solution", "count": len(population)})
