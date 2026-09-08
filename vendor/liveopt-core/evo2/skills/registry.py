from __future__ import annotations

from collections import defaultdict

from evo2.skills.base import Skill


class SkillRegistry:
    def __init__(self):
        self._skills = defaultdict(list)

    def register(self, skill: Skill) -> None:
        self._skills[skill.skill_type].append(skill)

    def get(self, skill_type: str):
        return list(self._skills.get(skill_type, []))

    def applicable(self, skill_type: str, context):
        return [s for s in self.get(skill_type) if s.applicable(context)]

    def planner_descriptions(self, skill_type: str, context=None):
        skills = self.applicable(skill_type, context) if context is not None else self.get(skill_type)
        return [s.planner_description() for s in skills]

    def by_id(self, skill_id: str):
        for skills in self._skills.values():
            for skill in skills:
                if skill.skill_id == skill_id:
                    return skill
        return None
