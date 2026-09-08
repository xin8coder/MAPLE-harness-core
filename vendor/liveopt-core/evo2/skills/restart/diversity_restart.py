from __future__ import annotations

from evo2.skills.base import Skill, SkillContext, SkillResult
from evo2.skills.restart._utils import operator_memory, solution_to_individual, universal_decoder


class DiversityRestartSkill(Skill):
    skill_id = "diversity_restart_v1"
    skill_type = "restart"
    description = "Preserve diverse representatives and mutate them to recover search diversity."
    suitable_change_scale = "medium"
    handles = ["low diversity populations", "premature convergence", "updates needing broader exploration"]
    limitations = ["requires previous population", "does not directly repair hard constraints"]
    planner_tags = ["diversity", "exploration", "medium_change"]

    def applicable(self, context: SkillContext) -> bool:
        summary = context.memory.get("population_summary", {})
        return context.previous_population is not None and summary.get("diversity_level") in {"low", "medium", None}

    def run(self, context: SkillContext) -> SkillResult:
        pop = context.previous_population
        reps = pop.diverse_representatives(k=int(context.budget.get("diverse_k", 10)))
        output = []
        decoder = universal_decoder(context)
        for ind in reps:
            output.append(ind)
            for j in range(2):
                sol = decoder.mutate_solution(ind.solution, operator_memory(context))
                output.append(solution_to_individual(sol, f"diverse_mut_{j}"))
        return SkillResult(True, output, {"restart": self.skill_id, "representatives": len(reps), "count": len(output)})
