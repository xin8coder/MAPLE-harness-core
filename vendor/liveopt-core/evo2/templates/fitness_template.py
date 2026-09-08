from __future__ import annotations

from typing import Any

from evo2.core.template_optimizer import violation_amount


def penalty_result(
    base_scalar: float,
    violations: dict[str, Any],
    *,
    objectives: list[float] | None = None,
    penalty_weight: float = 1_000_000.0,
    solution: dict[str, Any] | None = None,
    diagnostics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return the standard fitness payload used by generated evaluators."""

    penalty = penalty_weight * violation_amount(violations)
    return {
        "scalar": float(base_scalar) + penalty,
        "base_scalar": float(base_scalar),
        "penalty": penalty,
        "objectives": list(objectives or []),
        "feasible": penalty <= 0.0,
        "violations": violations,
        "solution": solution or {},
        "diagnostics": diagnostics or {},
    }


FITNESS_SLOT_TEMPLATE = '''
def evaluate(solution, data):
    """Problem-specific fitness slot filled by the LLM.

    Guidelines:
    - Read entities and parameters from `data`, not from hardcoded names.
    - Loop over resources, demands, assignments, routes, times, or selected items.
    - Compute public objective terms.
    - Build structured violations such as {"capacity": {"excess": 3.0}}.
    - Return penalty_result(base_scalar, violations, objectives=[...], solution=solution).
    """
    raise NotImplementedError("LLM must fill this slot")
'''.strip()
