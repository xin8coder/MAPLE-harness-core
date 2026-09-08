from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class SkillContext:
    task_id: str
    ir: Any
    previous_solution: Any | None = None
    previous_population: Any | None = None
    natural_language_update: str | None = None
    patches: List[Any] = field(default_factory=list)
    memory: Dict[str, Any] = field(default_factory=dict)
    budget: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    success: bool
    output: Any
    metadata: Dict[str, Any] = field(default_factory=dict)


class Skill(ABC):
    skill_id: str
    skill_type: str
    description: str = ""
    suitable_change_scale: str = "unknown"
    handles: List[str] = []
    limitations: List[str] = []
    planner_tags: List[str] = []

    def planner_description(self) -> Dict[str, Any]:
        return {
            "skill_id": self.skill_id,
            "skill_type": self.skill_type,
            "description": self.description or self.__class__.__doc__ or "",
            "suitable_change_scale": self.suitable_change_scale,
            "handles": list(self.handles),
            "limitations": list(self.limitations),
            "planner_tags": list(self.planner_tags),
        }

    @abstractmethod
    def applicable(self, context: SkillContext) -> bool:
        pass

    @abstractmethod
    def run(self, context: SkillContext) -> SkillResult:
        pass
