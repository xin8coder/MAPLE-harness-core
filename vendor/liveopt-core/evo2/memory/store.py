from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Dict, List

from evo2.memory.schemas import from_plain, to_plain


class MemoryStore:
    def save_problem_state(self, task_id: str, state: Dict[str, Any]) -> None:
        raise NotImplementedError

    def save_solution(self, task_id: str, solution: Dict[str, Any]) -> None:
        raise NotImplementedError

    def save_population_summary(self, task_id: str, summary: Dict[str, Any]) -> None:
        raise NotImplementedError

    def save_strategy_record(self, task_id: str, record: Dict[str, Any]) -> None:
        raise NotImplementedError

    def retrieve_relevant(self, query: Dict[str, Any], k: int = 5) -> List[Dict[str, Any]]:
        raise NotImplementedError


class JSONLMemoryStore(MemoryStore):
    """Small append-only JSONL memory store, keyed by task_id/change_type."""

    def __init__(self, root: str | Path = ".evo2_memory"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "memory.jsonl"

    def save_problem_state(self, task_id: str, state: Dict[str, Any]) -> None:
        self._append("problem_state", task_id, state)

    def save_solution(self, task_id: str, solution: Dict[str, Any]) -> None:
        self._append("solution", task_id, solution)

    def save_population_summary(self, task_id: str, summary: Dict[str, Any]) -> None:
        self._append("population_summary", task_id, summary)

    def save_strategy_record(self, task_id: str, record: Dict[str, Any]) -> None:
        self._append("strategy_record", task_id, record)

    def retrieve_relevant(self, query: Dict[str, Any], k: int = 5) -> List[Dict[str, Any]]:
        records = self._read_all()
        task_id = query.get("task_id")
        change_type = query.get("change_type")
        matched = []
        for rec in records:
            if task_id and rec.get("task_id") != task_id:
                continue
            payload = rec.get("payload", {})
            if change_type and payload.get("change_type") != change_type:
                continue
            matched.append(rec)
        return matched[-k:]

    def latest_by_type(self, task_id: str, record_type: str):
        for rec in reversed(self._read_all()):
            if rec.get("task_id") == task_id and rec.get("type") == record_type:
                return rec.get("payload", {})
        return None

    def load_context_memory(self, task_id: str) -> dict:
        records = self._read_all()
        relevant = [r for r in records if r.get("task_id") == task_id]
        state = next((r.get("payload", {}) for r in reversed(relevant) if r.get("type") == "problem_state"), {})
        solution = next((r.get("payload", {}) for r in reversed(relevant) if r.get("type") == "solution"), {})
        pop_summary = next((r.get("payload", {}) for r in reversed(relevant) if r.get("type") == "population_summary"), {})
        strategies = [r.get("payload", {}) for r in relevant if r.get("type") == "strategy_record"][-50:]
        solution_history = [r.get("payload", {}) for r in relevant if r.get("type") == "solution"][-50:]
        population_history = [r.get("payload", {}).get("population") for r in relevant if r.get("type") == "problem_state" and r.get("payload", {}).get("population") is not None][-20:]
        return {"problem_state": state, "solution_record": solution, "population_summary": pop_summary, "strategy_memory": strategies, "solution_history": solution_history, "population_history": population_history}

    def _append(self, record_type: str, task_id: str, payload: Dict[str, Any]) -> None:
        rec = {"type": record_type, "task_id": task_id, "timestamp": time.time(), "payload": to_plain(payload)}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def _read_all(self) -> list[dict]:
        if not self.path.exists():
            return []
        records = []
        with self.path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    records.append(from_plain(json.loads(line)))
        return records
