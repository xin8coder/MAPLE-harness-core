from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


SLOT_NAMES = ("setup.py", "data_adapter.py", "decode.py", "repair.py", "fitness.py")


@dataclass
class RepairFeedback:
    summary: str
    runtime_error: str = ""
    checks: list[str] = field(default_factory=list)

    def to_prompt_text(self) -> str:
        lines = [self.summary.strip()]
        if self.runtime_error:
            lines.append(f"runtime: {self.runtime_error.strip()}")
        for check in self.checks[:8]:
            lines.append(f"check: {check}")
        return "\n".join(line for line in lines if line)


def parse_code_slots(text: str) -> dict[str, str]:
    """Extract Workbench code slots from markdown-like LLM output."""

    slots: dict[str, str] = {}
    pattern = re.compile(
        r"^[ \t]*###\s*(setup\.py|data_adapter\.py|decode\.py|repair\.py|fitness\.py)\s*\n[ \t]*```(?:python)?\s*\n(.*?)\n[ \t]*```",
        re.IGNORECASE | re.MULTILINE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        slots[match.group(1).lower()] = match.group(2).strip()
    return slots


def merge_code_slots(current: dict[str, str], patch_text: str) -> dict[str, str]:
    merged = dict(current)
    merged.update(parse_code_slots(patch_text))
    return merged


def build_repair_feedback(
    *,
    runtime_error: str = "",
    search_spec_text: str = "",
    code_slots: dict[str, str] | None = None,
    data: dict[str, Any] | None = None,
) -> RepairFeedback:
    slots = code_slots or {}
    checks: list[str] = []
    entity_literals = _public_entity_literals(data or {})
    code_blob = "\n".join(slots.get(name, "") for name in SLOT_NAMES)
    for literal in sorted(entity_literals, key=str):
        if repr(str(literal)) in code_blob or f'"{literal}"' in code_blob:
            checks.append(f"entity literal {literal!r} appears in code; loop over data tables instead")
            break
    for line in search_spec_text.splitlines():
        line = line.strip()
        if line.upper().startswith("CON "):
            name = line[4:].strip().split()[0]
            if name and name not in code_blob:
                checks.append(f"constraint {name!r} is declared but not visibly handled")
    fitness = slots.get("fitness.py", "")
    if fitness and ("return 0" in fitness or "return {'scalar': 0" in fitness or 'return {"scalar": 0' in fitness):
        checks.append("fitness appears constant; compute objective terms and violation penalties from data")
    repair = slots.get("repair.py", "")
    if "optional_assignment" in search_spec_text and repair and "None" not in repair and "unassigned" not in repair:
        checks.append("optional assignment encoding needs explicit None/unassigned handling")
    return RepairFeedback(
        summary="repair generated slots with minimal changes",
        runtime_error=runtime_error,
        checks=checks,
    )


def _public_entity_literals(data: dict[str, Any]) -> set[str]:
    literals: set[str] = set()
    for rows in data.values():
        if isinstance(rows, dict) and isinstance(rows.get("rows"), list):
            rows = rows["rows"]
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            for key, value in row.items():
                if _entity_key(key) and isinstance(value, str) and _interesting_literal(value):
                    literals.add(value)
    return literals


def _entity_key(key: str) -> bool:
    key = str(key).lower()
    return key == "id" or key.endswith("_id") or key.endswith("_name") or key in {"name", "resource", "demand", "task", "job", "machine", "vehicle"}


def _interesting_literal(value: str) -> bool:
    text = value.strip()
    if len(text) < 2:
        return False
    return not text.lower() in {"none", "true", "false", "yes", "no"}
