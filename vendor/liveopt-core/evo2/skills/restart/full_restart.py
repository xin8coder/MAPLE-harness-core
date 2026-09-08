from __future__ import annotations

from evo2.skills.base import Skill, SkillContext, SkillResult
from evo2.skills.restart._utils import operator_memory, solution_to_individual, universal_decoder


class FullRestartSkill(Skill):
    skill_id = "full_restart_v1"
    skill_type = "restart"
    description = "Discard prior population and initialize a new random population for a full re-solve."
    suitable_change_scale = "large"
    handles = ["large structural changes", "major resource changes", "cold-start baselines", "when old solutions are misleading"]
    limitations = ["high disruption", "does not exploit memory", "usually higher search cost"]
    planner_tags = ["full_restart", "baseline", "large_change"]

    def applicable(self, context: SkillContext) -> bool:
        return True

    def run(self, context: SkillContext) -> SkillResult:
        size = int(context.budget.get("population_size", 20))
        decoder = universal_decoder(context)
        inds = [solution_to_individual(decoder.candidate_at(i, operator_memory(context)), f"full_candidate_{i}") for i in range(size)]
        return SkillResult(True, inds, {"restart": self.skill_id, "count": len(inds)})
