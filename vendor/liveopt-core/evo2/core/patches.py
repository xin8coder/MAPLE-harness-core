from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Literal

PatchType = Literal["model", "fitness", "search"]


@dataclass
class Patch:
    patch_id: str
    patch_type: PatchType
    reason: str
    payload: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)
