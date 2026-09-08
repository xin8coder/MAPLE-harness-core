from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, linprog, milp


@dataclass
class LinearProgrammingResult:
    success: bool
    status: str
    objective_value: float | None = None
    variable_values: dict[str, float] = field(default_factory=dict)
    lower_bound: float | None = None
    upper_bound: float | None = None
    gap: float | None = None
    message: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


class LinearProgrammingBackend:
    """Solve domain-neutral LP/MILP specs with SciPy HiGHS."""

    def solve(self, spec: dict[str, Any], time_limit: float | None = None) -> LinearProgrammingResult:
        variables = spec.get("variables", [])
        if not variables:
            raise ValueError("LP spec requires variables")
        names = [v["name"] if isinstance(v, dict) else str(v) for v in variables]
        name_to_idx = {name: i for i, name in enumerate(names)}
        c = np.array([float(_coef(spec.get("objective", {}), name)) for name in names], dtype=float)
        if spec.get("sense", spec.get("objective", {}).get("sense", "minimize")) in {"max", "maximize"}:
            c = -c

        lb = []
        ub = []
        integrality = []
        for var in variables:
            if not isinstance(var, dict):
                var = {"name": str(var)}
            typ = var.get("type", "continuous")
            lb.append(_bound_value(var.get("lb", 0.0), 0.0))
            ub.append(_bound_value(var.get("ub", np.inf), np.inf))
            integrality.append(1 if typ in {"binary", "integer", "int"} else 0)
            if typ == "binary":
                lb[-1] = max(lb[-1], 0.0)
                ub[-1] = min(ub[-1], 1.0)

        rows = []
        lower = []
        upper = []
        for con in spec.get("constraints", []):
            coeffs = con.get("coefficients", {})
            row = np.zeros(len(names), dtype=float)
            for name, value in coeffs.items():
                if name in name_to_idx:
                    row[name_to_idx[name]] = float(value)
            rhs = float(con.get("rhs", 0.0))
            sense = con.get("sense", "<=")
            if sense in {"<=", "le"}:
                lower.append(-np.inf)
                upper.append(rhs)
            elif sense in {">=", "ge"}:
                lower.append(rhs)
                upper.append(np.inf)
            elif sense in {"=", "==", "eq"}:
                lower.append(rhs)
                upper.append(rhs)
            else:
                raise ValueError(f"unsupported constraint sense: {sense}")
            rows.append(row)

        is_milp = any(integrality)
        options = {"time_limit": time_limit} if time_limit else None
        if is_milp:
            constraints = LinearConstraint(np.array(rows), np.array(lower), np.array(upper)) if rows else None
            res = milp(
                c=c,
                integrality=np.array(integrality),
                bounds=Bounds(np.array(lb), np.array(ub)),
                constraints=constraints,
                options=options,
            )
            values = _values(names, res.x)
            objective = _restore_objective(float(res.fun), spec) if res.fun is not None else None
            return LinearProgrammingResult(
                success=bool(res.success),
                status=str(res.status),
                objective_value=objective,
                variable_values=values,
                lower_bound=_restore_objective(float(getattr(res, "mip_dual_bound", np.nan)), spec) if getattr(res, "mip_dual_bound", None) is not None else None,
                upper_bound=objective,
                gap=float(getattr(res, "mip_gap", np.nan)) if getattr(res, "mip_gap", None) is not None else None,
                message=str(res.message),
                metadata={"solver": "scipy.milp", "raw_status": int(res.status)},
            )

        A_ub, b_ub, A_eq, b_eq = [], [], [], []
        for row, lo, hi in zip(rows, lower, upper):
            if lo == hi:
                A_eq.append(row)
                b_eq.append(hi)
            else:
                if hi < np.inf:
                    A_ub.append(row)
                    b_ub.append(hi)
                if lo > -np.inf:
                    A_ub.append(-row)
                    b_ub.append(-lo)
        res = linprog(
            c=c,
            A_ub=np.array(A_ub) if A_ub else None,
            b_ub=np.array(b_ub) if b_ub else None,
            A_eq=np.array(A_eq) if A_eq else None,
            b_eq=np.array(b_eq) if b_eq else None,
            bounds=list(zip(lb, ub)),
            method="highs",
            options=options,
        )
        objective = _restore_objective(float(res.fun), spec) if res.fun is not None else None
        return LinearProgrammingResult(
            success=bool(res.success),
            status=str(res.status),
            objective_value=objective,
            variable_values=_values(names, res.x),
            lower_bound=objective if res.success else None,
            upper_bound=objective if res.success else None,
            gap=0.0 if res.success else None,
            message=str(res.message),
            metadata={"solver": "scipy.linprog", "raw_status": int(res.status)},
        )


def _coef(objective: dict[str, Any], name: str) -> float:
    coeffs = objective.get("coefficients", objective)
    return float(coeffs.get(name, 0.0)) if isinstance(coeffs, dict) else 0.0


def _bound_value(value: Any, default: float) -> float:
    if value in (None, ""):
        return float(default)
    return float(value)


def _restore_objective(value: float, spec: dict[str, Any]) -> float:
    if spec.get("sense", spec.get("objective", {}).get("sense", "minimize")) in {"max", "maximize"}:
        return -value
    return value


def _values(names: list[str], x) -> dict[str, float]:
    if x is None:
        return {}
    return {name: float(value) for name, value in zip(names, x)}
