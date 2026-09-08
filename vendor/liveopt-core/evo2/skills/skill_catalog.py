from __future__ import annotations

import importlib
import json
import os
import re
from pathlib import Path
from typing import Any


DEFAULT_SKILL_CATALOG_ROOT = Path(__file__).resolve().parent / "catalog"
RUNTIME_BINDING_SCHEMA_VERSION = "liveopt_skill_runtime_binding_v1"


def load_skill_cards(root: str | Path | None = None) -> list[dict[str, Any]]:
    """Load planner-facing Markdown skill cards from a folder tree."""
    cards: list[dict[str, Any]] = []
    for catalog_root in skill_catalog_roots(root):
        if not catalog_root.exists():
            continue
        for path in sorted(catalog_root.rglob("SKILL.md")):
            text = path.read_text(encoding="utf-8")
            card = parse_skill_card(text, path)
            if card:
                cards.append(card)
    return cards


def skill_catalog_roots(root: str | Path | None = None) -> list[Path]:
    """Return default plus optional user-supplied skill catalog roots.

    Users can add folders without editing core code by setting
    ``LIVEOPT_SKILL_CATALOG_ROOTS`` to one or more paths separated by
    ``os.pathsep``.
    """
    if root is not None:
        return [Path(root)]
    roots = [DEFAULT_SKILL_CATALOG_ROOT]
    raw = os.getenv("LIVEOPT_SKILL_CATALOG_ROOTS", "")
    for item in raw.split(os.pathsep):
        item = item.strip()
        if item:
            roots.append(Path(item))
    deduped: list[Path] = []
    seen: set[str] = set()
    for candidate in roots:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key not in seen:
            deduped.append(candidate)
            seen.add(key)
    return deduped


def parse_skill_card(markdown: str, path: str | Path | None = None) -> dict[str, Any]:
    skill_id = _field(markdown, "Skill ID")
    skill_type = _field(markdown, "Skill Type")
    if not skill_id or not skill_type:
        return {}
    summary = _field(markdown, "Summary") or _first_paragraph(markdown)
    planner_tags = _csv(_field(markdown, "Planner Tags"))
    return {
        "skill_id": skill_id,
        "skill_type": skill_type,
        "description": summary,
        "summary": summary,
        "use_when": _section(markdown, "Use When"),
        "do_not_use_when": _section(markdown, "Do Not Use When"),
        "required_public_evidence": _section(markdown, "Required Public Evidence"),
        "required_artifact_fields": _section(markdown, "Required Artifact Fields"),
        "operating_procedure": _section(markdown, "Operating Procedure"),
        "selection_checklist": _section(markdown, "Selection Checklist"),
        "prompt_guidance": _section(markdown, "Prompt Guidance"),
        "minimal_example": _section(markdown, "Minimal Example"),
        "output_contract": _section(markdown, "Output Contract"),
        "failure_mode": _section(markdown, "Failure Mode"),
        "planner_tags": planner_tags,
        "skill_card_markdown": markdown.strip(),
        "catalog_source_path": str(path or ""),
    }


def skill_cards_by_id(root: str | Path | None = None) -> dict[str, dict[str, Any]]:
    return {card["skill_id"]: card for card in load_skill_cards(root)}


def load_runtime_bindings(root: str | Path | None = None) -> list[dict[str, Any]]:
    """Load optional runtime bindings colocated with skill cards."""
    bindings: list[dict[str, Any]] = []
    for catalog_root in skill_catalog_roots(root):
        if not catalog_root.exists():
            continue
        for path in sorted(catalog_root.rglob("runtime_binding.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            binding = normalize_runtime_binding(data, path)
            if binding:
                bindings.append(binding)
    return bindings


def normalize_runtime_binding(data: dict[str, Any], path: str | Path | None = None) -> dict[str, Any]:
    if not isinstance(data, dict):
        return {}
    skill_id = str(data.get("skill_id") or "").strip()
    skill_type = str(data.get("skill_type") or "").strip()
    if not skill_id or not skill_type:
        return {}
    binding = dict(data)
    binding.setdefault("schema_version", RUNTIME_BINDING_SCHEMA_VERSION)
    binding["skill_id"] = skill_id
    binding["skill_type"] = skill_type
    binding["runtime_binding_path"] = str(path or "")
    return binding


def runtime_bindings_by_id(root: str | Path | None = None, skill_type: str | None = None) -> dict[str, dict[str, Any]]:
    bindings: dict[str, dict[str, Any]] = {}
    for binding in load_runtime_bindings(root):
        if skill_type and binding.get("skill_type") != skill_type:
            continue
        bindings[str(binding["skill_id"])] = binding
    return bindings


def runtime_bound_skill_ids(skill_type: str | None = None, root: str | Path | None = None) -> set[str]:
    return set(runtime_bindings_by_id(root=root, skill_type=skill_type))


def instantiate_bound_skill_classes(skill_type: str, root: str | Path | None = None) -> dict[str, Any]:
    """Instantiate Skill subclasses declared by runtime_binding.json files."""
    instances: dict[str, Any] = {}
    for skill_id, binding in runtime_bindings_by_id(root=root, skill_type=skill_type).items():
        runtime = binding.get("runtime") if isinstance(binding.get("runtime"), dict) else {}
        if runtime.get("kind") != "skill_class":
            continue
        import_path = str(runtime.get("import_path") or "")
        if not import_path:
            raise ValueError(f"runtime binding for {skill_id} is missing runtime.import_path")
        kwargs = runtime.get("init_kwargs") if isinstance(runtime.get("init_kwargs"), dict) else {}
        cls = import_from_path(import_path)
        instance = cls(**kwargs)
        if getattr(instance, "skill_id", skill_id) != skill_id:
            instance.skill_id = skill_id
        if getattr(instance, "skill_type", skill_type) != skill_type:
            instance.skill_type = skill_type
        instances[skill_id] = instance
    return instances


def import_from_path(import_path: str) -> Any:
    module_name, sep, attr = import_path.partition(":")
    if not sep:
        module_name, _, attr = import_path.rpartition(".")
    if not module_name or not attr:
        raise ValueError(f"invalid import path {import_path!r}; expected module:attribute")
    module = importlib.import_module(module_name)
    value: Any = module
    for part in attr.split("."):
        value = getattr(value, part)
    return value


def search_space_runtime_bindings(root: str | Path | None = None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for skill_id, binding in runtime_bindings_by_id(root=root, skill_type="search_space").items():
        spec = binding.get("search_space") if isinstance(binding.get("search_space"), dict) else {}
        if not spec:
            continue
        task_type = str(spec.get("task_type") or skill_id)
        merged = dict(spec)
        merged.setdefault("task_type", task_type)
        merged.setdefault("skill_id", skill_id)
        merged.setdefault("runtime_binding_path", binding.get("runtime_binding_path", ""))
        out[task_type] = merged
    return out


def merge_skill_cards(
    descriptions: list[dict[str, Any]],
    root: str | Path | None = None,
    include_unreferenced: bool = True,
) -> list[dict[str, Any]]:
    """Merge Markdown cards into runtime planner descriptions.

    Existing executable skills keep their runtime fields; Markdown cards add
    public selection criteria and source paths. Cards without a matching runtime
    skill are still surfaced as search-space or method-planning skills.
    """
    cards = skill_cards_by_id(root)
    bindings = runtime_bindings_by_id(root)
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in descriptions:
        if not isinstance(item, dict):
            continue
        skill_id = str(item.get("skill_id") or item.get("id") or item.get("name") or "")
        if not skill_id:
            continue
        card = cards.get(skill_id)
        updated = dict(item)
        if card:
            updated = _merge_one(updated, card)
        if skill_id in bindings:
            updated = _merge_runtime_binding_summary(updated, bindings[skill_id])
        merged.append(updated)
        seen.add(skill_id)
    if include_unreferenced:
        for skill_id in sorted(cards):
            if skill_id not in seen:
                updated = dict(cards[skill_id])
                if skill_id in bindings:
                    updated = _merge_runtime_binding_summary(updated, bindings[skill_id])
                merged.append(updated)
    return merged


def _merge_one(runtime: dict[str, Any], card: dict[str, Any]) -> dict[str, Any]:
    merged = dict(runtime)
    merged.setdefault("description", card.get("description", ""))
    merged["catalog_summary"] = card.get("summary", "")
    merged["skill_card_markdown"] = card.get("skill_card_markdown", "")
    merged["catalog_source_path"] = card.get("catalog_source_path", "")
    for key in [
        "use_when",
        "do_not_use_when",
        "required_public_evidence",
        "required_artifact_fields",
        "operating_procedure",
        "selection_checklist",
        "prompt_guidance",
        "minimal_example",
        "output_contract",
        "failure_mode",
    ]:
        if card.get(key):
            merged[key] = card[key]
    merged["planner_tags"] = sorted(
        {
            str(tag)
            for tag in list(runtime.get("planner_tags", []) or []) + list(card.get("planner_tags", []) or [])
            if str(tag)
        }
    )
    return merged


def _merge_runtime_binding_summary(item: dict[str, Any], binding: dict[str, Any]) -> dict[str, Any]:
    merged = dict(item)
    runtime = binding.get("runtime") if isinstance(binding.get("runtime"), dict) else {}
    merged["runtime_bound"] = True
    merged["runtime_binding_path"] = binding.get("runtime_binding_path", "")
    merged["runtime_kind"] = runtime.get("kind") or binding.get("skill_type")
    if runtime.get("import_path"):
        merged["runtime_import_path"] = runtime.get("import_path")
    for key in ["search_space"]:
        if isinstance(binding.get(key), dict):
            merged[f"{key}_binding"] = binding[key]
    return merged


def _field(markdown: str, name: str) -> str:
    pattern = re.compile(rf"^\s*{re.escape(name)}\s*:\s*(.*?)\s*$", re.IGNORECASE | re.MULTILINE)
    match = pattern.search(markdown)
    return match.group(1).strip() if match else ""


def _section(markdown: str, heading: str) -> list[str]:
    pattern = re.compile(
        rf"^##\s+{re.escape(heading)}\s*$([\s\S]*?)(?=^##\s+|\Z)",
        re.IGNORECASE | re.MULTILINE,
    )
    match = pattern.search(markdown)
    if not match:
        return []
    lines: list[str] = []
    for raw in match.group(1).splitlines():
        line = raw.strip()
        if not line:
            continue
        line = re.sub(r"^[-*]\s+", "", line)
        if line:
            lines.append(line)
    return lines


def _first_paragraph(markdown: str) -> str:
    for block in re.split(r"\n\s*\n", markdown.strip()):
        text = " ".join(line.strip() for line in block.splitlines() if line.strip() and not line.startswith("#"))
        if text and ":" not in text[:32]:
            return text
    return ""


def _csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]
