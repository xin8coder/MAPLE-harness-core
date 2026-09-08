from __future__ import annotations


def similar_update_records(memory: dict, change_types: list[str]) -> list[dict]:
    records = memory.get("strategy_memory", [])
    wanted = set(change_types)
    return [r for r in records if r.get("change_type") in wanted]
