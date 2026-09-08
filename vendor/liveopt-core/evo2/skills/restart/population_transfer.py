from __future__ import annotations

from evo2.skills.base import Skill, SkillContext, SkillResult
from evo2.skills.restart._utils import repair_individual


class PopulationTransferSkill(Skill):
    skill_id = "population_transfer_v1"
    skill_type = "restart"
    description = "Transfer and repair the previous population as the initial population for the new stage."
    suitable_change_scale = "small-to-medium"
    handles = ["moderate dynamic updates", "objective changes", "soft constraint changes", "when previous population remains relevant"]
    limitations = ["can preserve stale individuals after large changes", "requires previous population"]
    planner_tags = ["population_reuse", "memory_seeded", "medium_change"]

    def applicable(self, context: SkillContext) -> bool:
        return context.previous_population is not None

    def run(self, context: SkillContext) -> SkillResult:
        new_individuals = [repair_individual(ind, context) for ind in context.previous_population.individuals]
        return SkillResult(True, new_individuals, {"restart": self.skill_id, "transferred_count": len(new_individuals)})
