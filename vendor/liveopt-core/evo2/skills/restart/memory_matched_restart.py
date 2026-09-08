from __future__ import annotations

from evo2.skills.base import Skill, SkillContext, SkillResult


class MemoryMatchedRestartSkill(Skill):
    skill_id = "memory_matched_restart_v1"
    skill_type = "restart"
    description = "Reuse candidates from similar historical updates retrieved from memory."
    suitable_change_scale = "memory-dependent small-to-medium"
    handles = ["updates referring to earlier cases", "recurring patterns", "personalized or historical constraints"]
    limitations = ["requires retrieved similar update records", "weak when no comparable history exists"]
    planner_tags = ["retrieval", "memory_reference", "case_based"]

    def applicable(self, context: SkillContext) -> bool:
        return bool(context.memory.get("similar_update_records"))

    def run(self, context: SkillContext) -> SkillResult:
        records = context.memory.get("similar_update_records", [])
        best = min(records, key=lambda r: r.get("disruption", 1e9)) if records else {}
        candidate_ids = set(best.get("robust_candidate_ids", []))
        candidates = []
        if candidate_ids and context.previous_population:
            for ind in context.previous_population.individuals:
                if ind.individual_id in candidate_ids or ind.solution.solution_id in candidate_ids:
                    candidates.append(ind)
        return SkillResult(True, candidates, {"restart": self.skill_id, "matched_record": best, "count": len(candidates)})
