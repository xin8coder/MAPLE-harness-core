from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict


@dataclass
class Solution:
    solution_id: str
    assignments: Dict[str, Any]
    objective_value: float | None = None
    feasible: bool = False
    violations: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)
