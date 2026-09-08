"""Deterministic offline client for the demo's tests and dry-run mode.

``FakeDemoClient`` implements the same ``chat()`` contract as the provider
clients but never touches the network. It recognizes each LiveOpt sub-agent
and each chat-agent role by its system prompt and returns canned responses
that satisfy the real parsers (workbench slots, localizer JSON, data-patch
JSON, semantic-gate JSON, router JSON, summarizer text, plain chat replies).
The canned Workbench solves a small knapsack whose data lives in
``public_context['tables']``: the items are read from the first table with
``value``/``weight`` columns and the capacity from the first row anywhere
with a ``capacity`` column (user-imported table names are not fixed).
"""

from __future__ import annotations

import json
from typing import Any

SETUP_CODE = '''
def build_problem(public_context):
    tables = public_context["tables"]
    items = None
    capacity = None
    for rows in tables.values():
        if rows and items is None and "value" in rows[0] and "weight" in rows[0]:
            items = [dict(row) for row in rows]
        if rows and capacity is None and "capacity" in rows[0]:
            capacity = float(rows[0]["capacity"])
    data = {"items": items or [], "capacity": capacity if capacity is not None else 0.0}
    return {
        "data": data,
        "segments": [
            {
                "name": "select",
                "kind": "choice_vector",
                "length": len(items),
                "options": [0, 1],
            }
        ],
        "solver_mode": "scalar_ga",
        "sense": "min",
        "objective_names": ["negative_value"],
        "constraint_names": ["capacity"],
    }
'''

FITNESS_CODE = '''
def evaluate(genome, data):
    selected = [index for index, flag in enumerate(genome["select"]) if flag]
    total_value = sum(float(data["items"][index]["value"]) for index in selected)
    total_weight = sum(float(data["items"][index]["weight"]) for index in selected)
    violations = {}
    excess = total_weight - data["capacity"]
    if excess > 0:
        violations["capacity_excess"] = excess
    solution = {
        "selected_items": [data["items"][index]["id"] for index in selected],
        "total_value": total_value,
        "total_weight": total_weight,
    }
    return penalty_result(-total_value, violations, objectives=[-total_value], solution=solution)
'''


def _slots_response() -> str:
    return (
        "### setup.py\n```python\n" + SETUP_CODE.strip() + "\n```\n"
        "### fitness.py\n```python\n" + FITNESS_CODE.strip() + "\n```\n"
    )


class FakeDemoClient:
    """Offline stand-in for DeepSeekDebugClient/KimiK3Client."""

    def __init__(self, model: str = "fake-demo"):
        self.model = model
        self.payloads: list[dict[str, Any]] = []
        self.data_patch_count = 0

    def chat(
        self,
        messages: list[dict[str, str]],
        temperature: float = 0.0,
        max_tokens: int = 1024,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        system = next((str(m.get("content") or "") for m in messages if m.get("role") == "system"), "")
        content = self._respond(system, messages)
        self.payloads.append(
            {
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_mode": json_mode,
                "response": content,
            }
        )
        return {
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": sum(len(str(m.get("content") or "")) // 4 for m in messages),
                "completion_tokens": len(content) // 4,
                "total_tokens": (sum(len(str(m.get("content") or "")) // 4 for m in messages)) + len(content) // 4,
            },
        }

    def _respond(self, system: str, messages: list[dict[str, str]]) -> str:
        if "convert user-provided data into a structured optimization episode" in system:
            return json.dumps(
                {
                    "episode_id": "imported_knapsack",
                    "public_initial_problem": (
                        "Select a subset of items maximizing total value subject to total weight not "
                        "exceeding the capacity in the constraints table. Items live in the items table "
                        "with columns id, value, weight.\n\nScoring rules:\n- Maximize total value of "
                        "selected items.\n- Total weight must not exceed constraints.capacity."
                    ),
                    "objective": {
                        "objective_mode": "single_objective",
                        "objective_sense": "maximize",
                        "objective_names": ["total_value"],
                        "hard_constraints": ["Total weight of selected items must not exceed capacity."],
                        "objective_terms": [
                            {"name": "total_value", "formula": "sum(select[i] * items.value[i])", "source": "items table"}
                        ],
                        "scalar_formula": "total_value",
                        "solution_output_format": "JSON object with selected_items as a list of item ids",
                    },
                }
            )
        if "router for a LiveOpt chat agent" in system:
            return self._router_response(messages)
        if "summarize the result of a LiveOpt tool call" in system:
            return "Applied the tool call and committed the updated plan (fake summarizer)."
        if "LiveOpt Assistant" in system:
            last_user = next(
                (str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"),
                "",
            )
            return f"Fake assistant reply to: {last_user[:120]}"
        if "fill setup.py and fitness.py slots" in system:
            return _slots_response()
        if "Classify dynamic optimization updates" in system:
            return json.dumps(
                {
                    "data_update": True,
                    "patch_setup": False,
                    "patch_fitness": False,
                    "restart_skill": "warm_restart_v1",
                    "reason": "fake localizer: the update only changes public table values",
                    "state_binding_queries": [],
                }
            )
        if "Patch public optimization data" in system:
            self.data_patch_count += 1
            return json.dumps(
                {
                    "operations": [
                        {
                            "op": "update_row",
                            "path": ["tables", "items"],
                            "match": {"id": "I1"},
                            "values": {"value": 10 + 5 * self.data_patch_count},
                        }
                    ]
                }
            )
        if "semantic channel" in system:
            return json.dumps(
                {
                    "reuse_risk": "low",
                    "change_mechanisms": [],
                    "full_vote": False,
                    "evidence_paths": [],
                    "reason": "fake gate: a single value edit keeps the previous basin useful",
                }
            )
        if "Patch only requested Python code slots" in system or "Regenerate complete standalone" in system:
            return _slots_response()
        raise RuntimeError(f"FakeDemoClient cannot answer system prompt: {system[:80]!r}")

    def _router_response(self, messages: list[dict[str, str]]) -> str:
        user_prompt = next(
            (str(m.get("content") or "") for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        text = user_prompt.split("User message:", 1)[-1].strip()
        if "Optimization session active: yes" in user_prompt:
            return json.dumps({"action": "apply_update", "update": text})
        lowered = text.lower()
        if "import" in lowered or "my data" in lowered:
            return json.dumps({"action": "import_data", "goal": text})
        if any(keyword in lowered for keyword in ("optimiz", "knapsack", "schedule", "capacity", "maximize", "minimize")):
            return json.dumps({"action": "start_optimization", "problem": text})
        return json.dumps({"action": "answer"})


def fake_client_factory(**kwargs: Any) -> FakeDemoClient:
    """Client-factory hook matching ``demo.session.build_client``."""

    return FakeDemoClient(model=str(kwargs.get("model") or "fake-demo"))
