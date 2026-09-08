from __future__ import annotations

from typing import Callable

from evo2.core.patches import Patch


class FitnessFunction:
    """Composable minimization fitness function."""

    def __init__(self, weights: dict | None = None):
        self.weights = weights or {}
        self.terms: list[tuple[str, Callable, float]] = []

    def add_term(self, name: str, fn: Callable, weight: float = 1.0):
        self.terms.append((name, fn, weight))
        return self

    def evaluate(self, solution, context) -> float:
        total = 0.0
        for name, fn, weight in self.terms:
            total += self.weights.get(name, weight) * fn(solution, context)
        return float(total)

    def apply_patch(self, patch: Patch):
        if patch.patch_type != "fitness":
            return self
        payload = patch.payload
        for key, value in payload.get("modify_weights", {}).items():
            self.weights[key] = float(value)
        for term in payload.get("add_terms", []):
            name = term.get("name")
            weight = float(term.get("weight", 1.0))
            if name == "urgent_order_delay_penalty":
                order_id = term.get("order_id")
                self.add_term(name, lambda sol, ctx, oid=order_id: urgent_order_delay_penalty(sol, ctx, oid), weight)
            elif name == "disruption_penalty":
                self.add_term(name, lambda sol, ctx: assignment_disruption(ctx.previous_solution, sol) if getattr(ctx, "previous_solution", None) else 0, weight)
        return self


def assignment_disruption(old_solution, new_solution) -> int:
    if old_solution is None or new_solution is None:
        return 0
    old = old_solution.assignments.get("worker_shift", {})
    new = new_solution.assignments.get("worker_shift", {})
    keys = set(old) | set(new)
    return sum(1 for k in keys if old.get(k) != new.get(k))


def urgent_order_delay_penalty(solution, context, order_id: str | None) -> float:
    if not order_id:
        return 0.0
    ir = context.ir
    orders = {o["id"]: o for o in ir.entities.get("orders", [])}
    order = orders.get(order_id, {})
    due_rank = order.get("due_rank")
    slot = solution.assignments.get("order_slot", {}).get(order_id)
    if slot is None or due_rank is None:
        return 1.0
    slot_rank = ir.metadata.get("slot_ranks", {}).get(slot, due_rank)
    return max(0, slot_rank - due_rank)
