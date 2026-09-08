from __future__ import annotations

from dataclasses import fields, is_dataclass
from typing import Any

from evo2.core.population import Individual, Population
from evo2.core.solution import Solution


def to_plain(obj: Any) -> Any:
    if is_dataclass(obj):
        data = {f.name: to_plain(getattr(obj, f.name)) for f in fields(obj)}
        data["__class__"] = obj.__class__.__name__
        return data
    if isinstance(obj, dict):
        return {k: to_plain(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [to_plain(v) for v in obj]
    return obj


def from_plain(obj: Any) -> Any:
    if isinstance(obj, list):
        return [from_plain(v) for v in obj]
    if not isinstance(obj, dict):
        return obj
    cls = obj.get("__class__")
    data = {k: from_plain(v) for k, v in obj.items() if k != "__class__"}
    if cls == "Solution":
        return Solution(**data)
    if cls == "Individual":
        return Individual(**data)
    if cls == "Population":
        return Population(**data)
    return data
