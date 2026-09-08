"""Narrow provider-format compatibility installed only inside the sidecar."""

from __future__ import annotations

import ast
import json
import math
import os
import re
import threading
import time
from contextlib import contextmanager
from collections.abc import Callable, Iterator
from typing import Any

from evo2.agents import code_slots
from evo2.agents.llm_client import create_llm_client
from evo2.agents.liveopt_workbench_impl import ScaffoldTrace
from evo2.backends.linear_programming_backend import LinearProgrammingBackend
from evo2.core import template_optimizer


_ORIGINAL_PARSE_CODE_SLOTS = code_slots.parse_code_slots
_ORIGINAL_LINEAR_SOLVE = LinearProgrammingBackend.solve
_ORIGINAL_HISTORY_ROW = template_optimizer._history_row
_ORIGINAL_COMPILE_SLOT: Callable[..., Any] | None = None
_ORIGINAL_LOCALIZER_PROMPT: Callable[..., str] | None = None
_ORIGINAL_HARDCODED_ENTITY_CHECK: Callable[..., dict[str, list[str]]] | None = None
_ORIGINAL_RESTART_BUILD: Callable[..., Any] | None = None
_PROGRESS_LOCAL = threading.local()
_RESTART_PROGRESS_LOCAL = threading.local()
_INSTALLED = False


_SLOT_HEADING = re.compile(
    r"^[ \t]*###\s*(setup\.py|data_adapter\.py|decode\.py|repair\.py|fitness\.py)\s*$",
    re.IGNORECASE | re.MULTILINE,
)


def parse_code_slots_compat(text: str) -> dict[str, str]:
    """Accept JSON or fenced slots, including responses with nested fences."""

    payload = _json_object(text)
    if isinstance(payload, dict):
        slots = {
            name: sanitize_code_slot(value)
            for name, value in payload.items()
            if name in code_slots.SLOT_NAMES and isinstance(value, str) and value.strip()
        }
        if slots:
            return slots

    slots = _heading_code_slots(str(text or ""))
    if not slots:
        slots = _ORIGINAL_PARSE_CODE_SLOTS(text)
    return {
        name: sanitize_code_slot(value)
        for name, value in slots.items()
        if name in code_slots.SLOT_NAMES and isinstance(value, str) and value.strip()
    }


def sanitize_code_slot(code: str) -> str:
    """Remove Markdown fence lines; they are never valid Workbench Python."""

    return "\n".join(
        line for line in str(code or "").splitlines() if not line.strip().startswith("```")
    ).strip()


class StructuredWorkbenchPatcher:
    """Application patcher that exchanges slots as one JSON object."""

    def __init__(self, model: str = "deepseek-v4-flash", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)

    def patch_slots(
        self,
        *,
        current_slots: dict[str, str],
        natural_language_update: str,
        impact: Any,
        public_context: dict[str, Any],
        previous_error: str = "",
    ) -> tuple[dict[str, str], ScaffoldTrace]:
        from evo2.agents.liveopt_dynamic_impl import build_scaffold_patch_prompt

        trace = ScaffoldTrace(model=self.model)
        if not (impact.patch_setup or impact.patch_fitness):
            return dict(current_slots), trace
        required = []
        if impact.patch_setup:
            required.append("setup.py")
        if impact.patch_fitness:
            required.append("fitness.py")
        prompt = build_scaffold_patch_prompt(
            current_slots=current_slots,
            natural_language_update=natural_language_update,
            impact=impact,
            public_context=public_context,
            previous_error=previous_error,
        )
        prompt = prompt.replace(
            "Return only requested code blocks using headings like ### fitness.py.",
            "Return the requested complete slot sources in the JSON object described below.",
        )
        prompt += (
            "\n\nApplication output contract:\n"
            "Return exactly one JSON object. Each requested filename is a key and its complete "
            "raw Python source is the string value. Do not emit Markdown fences, prose, diffs, "
            "or unrequested slots. Required keys: "
            + ", ".join(required)
            + ". Any violations dictionary must be sparse: omit satisfied or zero-valued "
            "constraints and include only active positive violations."
        )
        trace.prompts.append(prompt)
        started = time.perf_counter()
        full_regeneration = bool(
            (getattr(impact, "raw", None) or {}).get("typed_full_regeneration_control")
        )
        system = (
            "Regenerate complete standalone Python slots for a fixed LiveOpt Workbench. "
            if full_regeneration
            else "Patch only requested Python code slots for a fixed LiveOpt Workbench. "
        )
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": system + "Return exactly one JSON object containing raw Python strings.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=5000,
            json_mode=True,
        )
        trace.latency_seconds = time.perf_counter() - started
        trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
        content = (
            response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if isinstance(response, dict)
            else ""
        )
        trace.raw_responses.append(content)
        slots = parse_code_slots_compat(content)
        missing = [name for name in required if name not in slots]
        if missing:
            raise ValueError(
                "structured slot response is missing requested keys: " + ", ".join(missing)
            )
        merged = dict(current_slots)
        merged.update(slots)
        return merged, trace


def install_provider_compatibility() -> None:
    """Install application-only parser and interactive-solver compatibility."""

    global _INSTALLED, _ORIGINAL_COMPILE_SLOT, _ORIGINAL_LOCALIZER_PROMPT
    global _ORIGINAL_HARDCODED_ENTITY_CHECK, _ORIGINAL_RESTART_BUILD
    if _INSTALLED:
        return
    from evo2.agents import liveopt_dynamic_impl, liveopt_workbench_impl

    code_slots.parse_code_slots = parse_code_slots_compat
    liveopt_workbench_impl.parse_code_slots = parse_code_slots_compat
    liveopt_dynamic_impl.parse_code_slots = parse_code_slots_compat
    _ORIGINAL_COMPILE_SLOT = liveopt_workbench_impl._compile_slot
    liveopt_workbench_impl._compile_slot = _compile_slot_with_diagnostics
    _ORIGINAL_LOCALIZER_PROMPT = liveopt_dynamic_impl.build_update_localizer_prompt
    liveopt_dynamic_impl.build_update_localizer_prompt = _data_first_localizer_prompt
    _ORIGINAL_HARDCODED_ENTITY_CHECK = (
        liveopt_dynamic_impl._slots_with_hardcoded_public_entity_ids
    )
    liveopt_dynamic_impl._slots_with_hardcoded_public_entity_ids = (
        _hardcoded_public_entity_ids_compat
    )
    _ORIGINAL_RESTART_BUILD = liveopt_dynamic_impl.ScaffoldRestartSeedBuilder.build
    liveopt_dynamic_impl.ScaffoldRestartSeedBuilder.build = _restart_build_with_progress
    original_solver_time_limit = liveopt_workbench_impl._solver_time_limit

    def interactive_solver_time_limit(problem_spec: dict[str, Any]) -> float | None:
        configured = original_solver_time_limit(problem_spec)
        if configured is not None:
            return configured
        return max(
            1.0,
            float(os.getenv("LIVEOPT_MCP_SOLVER_TIME_LIMIT_SECONDS", "30")),
        )

    def solve_with_verified_incumbent(
        backend: LinearProgrammingBackend,
        spec: dict[str, Any],
        time_limit: float | None = None,
    ):
        result = _ORIGINAL_LINEAR_SOLVE(backend, spec, time_limit=time_limit)
        if result.success or not time_limit or not result.variable_values:
            return result
        if "time limit" not in str(result.message).lower():
            return result
        verification = verify_linear_solution(spec, result.variable_values)
        if not verification["feasible"]:
            return result
        original_status = result.status
        result.success = True
        result.status = "time_limit_feasible"
        result.metadata = {
            **dict(result.metadata or {}),
            "optimal": False,
            "termination": "time_limit",
            "original_status": original_status,
            "feasibility_verification": verification,
        }
        return result

    liveopt_workbench_impl._solver_time_limit = interactive_solver_time_limit
    LinearProgrammingBackend.solve = solve_with_verified_incumbent
    template_optimizer._history_row = _history_row_with_progress
    _INSTALLED = True


def _compile_slot_with_diagnostics(code: str, function_name: str) -> Callable[..., Any]:
    """Report the exact slot line before the paper compiler executes it."""

    cleaned = sanitize_code_slot(code)
    try:
        ast.parse(cleaned, filename=f"<scaffold_slot_{function_name}>", mode="exec")
    except SyntaxError as exc:
        source_line = ""
        lines = cleaned.splitlines()
        if exc.lineno and 0 < exc.lineno <= len(lines):
            source_line = lines[exc.lineno - 1].strip()
        raise ValueError(
            f"slot {function_name} has invalid Python at line {exc.lineno}, "
            f"column {exc.offset}: {exc.msg}; source={source_line!r}. "
            "Return raw Python only and do not include any Markdown fence line."
        ) from exc
    if _ORIGINAL_COMPILE_SLOT is None:
        raise RuntimeError("LiveOpt slot compiler compatibility was not initialized")
    return _ORIGINAL_COMPILE_SLOT(cleaned, function_name)


def _data_first_localizer_prompt(**kwargs: Any) -> str:
    if _ORIGINAL_LOCALIZER_PROMPT is None:
        raise RuntimeError("LiveOpt localizer compatibility was not initialized")
    return _ORIGINAL_LOCALIZER_PROMPT(**kwargs) + "\n" + "\n".join(
        [
            "Application data-first rule:",
            "- A row addition, removal, activation, deactivation, or parameter edit in an existing public table is a data update. Set data_update=true and patch_setup=false when the existing setup.py derives segments and data by looping over that table; recompilation will rebuild segment domains from the patched rows.",
            "- Changing the number or membership of public resources does not by itself require new Python source. Set patch_setup=true only when the public schema, segment kind, or encoding logic changes.",
            "- Never regenerate setup.py merely to add, remove, or rename one public entity identifier.",
        ]
    )


def _hardcoded_public_entity_ids_compat(
    slots: dict[str, str], public_context: dict[str, Any]
) -> dict[str, list[str]]:
    """Keep entity checks while exempting genuine public schema references."""

    if _ORIGINAL_HARDCODED_ENTITY_CHECK is None:
        return {}
    violations = _ORIGINAL_HARDCODED_ENTITY_CHECK(slots, public_context)
    schema_names = _public_schema_names(public_context)
    return {
        slot: [literal for literal in literals if literal not in schema_names]
        for slot, literals in violations.items()
        if any(literal not in schema_names for literal in literals)
    }


@contextmanager
def evolution_progress(
    callback: Callable[[dict[str, Any]], None] | None,
    *,
    total_generations: int,
) -> Iterator[None]:
    """Bind a per-thread progress sink around an application optimization call."""

    previous = getattr(_PROGRESS_LOCAL, "binding", None)
    _PROGRESS_LOCAL.binding = {
        "callback": callback,
        "total_generations": max(0, int(total_generations)),
    }
    try:
        yield
    finally:
        if previous is None:
            try:
                del _PROGRESS_LOCAL.binding
            except AttributeError:
                pass
        else:
            _PROGRESS_LOCAL.binding = previous


@contextmanager
def restart_progress(
    callback: Callable[[dict[str, Any]], None] | None,
) -> Iterator[None]:
    """Observe the selected application restart immediately before search."""

    previous = getattr(_RESTART_PROGRESS_LOCAL, "callback", None)
    _RESTART_PROGRESS_LOCAL.callback = callback
    try:
        yield
    finally:
        if previous is None:
            try:
                del _RESTART_PROGRESS_LOCAL.callback
            except AttributeError:
                pass
        else:
            _RESTART_PROGRESS_LOCAL.callback = previous


def _restart_build_with_progress(*args: Any, **kwargs: Any) -> Any:
    if _ORIGINAL_RESTART_BUILD is None:
        raise RuntimeError("LiveOpt restart compatibility was not initialized")
    result = _ORIGINAL_RESTART_BUILD(*args, **kwargs)
    initial_genomes, raw_metadata = result
    metadata = dict(raw_metadata or {})
    callback = getattr(_RESTART_PROGRESS_LOCAL, "callback", None)
    if callable(callback):
        restart_skill = str(
            kwargs.get("restart_skill") or metadata.get("restart_skill") or ""
        )
        try:
            callback(
                {
                    "restart_skill": restart_skill,
                    "restart_source": metadata.get("source"),
                    "reused_solution_count": int(
                        metadata.get("feasible_seed_count")
                        or metadata.get("seed_count")
                        or len(initial_genomes or [])
                    ),
                    "history_population_ratio": metadata.get(
                        "realized_history_population_ratio",
                        metadata.get("history_population_ratio"),
                    ),
                    "fresh_population_ratio": metadata.get(
                        "realized_fresh_population_ratio",
                        metadata.get("fresh_population_ratio"),
                    ),
                }
            )
        except Exception:
            pass
    return result


def _history_row_with_progress(*args: Any, **kwargs: Any) -> dict[str, Any]:
    row = _ORIGINAL_HISTORY_ROW(*args, **kwargs)
    binding = getattr(_PROGRESS_LOCAL, "binding", None)
    if not isinstance(binding, dict) or not callable(binding.get("callback")):
        return row
    generation = int(row.get("generation") or 0)
    total = int(binding.get("total_generations") or 0)
    archive = kwargs.get("archive")
    best_scalar = row.get("best_scalar")
    if isinstance(best_scalar, (int, float)) and not math.isfinite(float(best_scalar)):
        best_scalar = None
    payload = {
        "generation": generation,
        "total_generations": total,
        "percent": round(100.0 * generation / total, 1) if total > 0 else 100.0,
        "population_size": int(row.get("population") or 0),
        "feasible_count": int(row.get("feasible") or 0),
        "archive_size": len(archive) if isinstance(archive, list) else 0,
        "front_size": int(row.get("front_size") or 0),
        "best_scalar": best_scalar,
    }
    try:
        binding["callback"](payload)
    except Exception:
        # UI progress is observational and must never change optimization behavior.
        pass
    return row


def verify_linear_solution(
    spec: dict[str, Any], values: dict[str, float], *, tolerance: float = 1e-6
) -> dict[str, Any]:
    """Verify a solver incumbent against a domain-neutral LP/MILP specification."""

    variables = [item for item in spec.get("variables", []) if isinstance(item, dict)]
    expected = [str(item.get("name")) for item in variables if item.get("name")]
    missing = [name for name in expected if name not in values]
    non_finite: list[str] = []
    max_bound_violation = 0.0
    max_integrality_violation = 0.0
    for variable in variables:
        name = str(variable.get("name") or "")
        if not name or name not in values:
            continue
        value = float(values[name])
        if not math.isfinite(value):
            non_finite.append(name)
            continue
        lower = _finite_bound(variable.get("lb"), 0.0)
        upper = _finite_bound(variable.get("ub"), math.inf)
        max_bound_violation = max(
            max_bound_violation,
            max(0.0, lower - value),
            max(0.0, value - upper),
        )
        if str(variable.get("type", "continuous")).lower() in {
            "binary",
            "integer",
            "int",
        }:
            max_integrality_violation = max(
                max_integrality_violation, abs(value - round(value))
            )

    max_constraint_violation = 0.0
    unsupported_senses: list[str] = []
    for constraint in spec.get("constraints", []):
        if not isinstance(constraint, dict):
            continue
        coefficients = constraint.get("coefficients", {})
        if not isinstance(coefficients, dict):
            coefficients = {}
        lhs = sum(
            float(coefficient) * float(values.get(str(name), 0.0))
            for name, coefficient in coefficients.items()
        )
        rhs = float(constraint.get("rhs", 0.0))
        sense = str(constraint.get("sense", "<=")).lower()
        if sense in {"<=", "le"}:
            violation = max(0.0, lhs - rhs)
        elif sense in {">=", "ge"}:
            violation = max(0.0, rhs - lhs)
        elif sense in {"=", "==", "eq"}:
            violation = abs(lhs - rhs)
        else:
            unsupported_senses.append(sense)
            violation = math.inf
        scale = max(1.0, abs(lhs), abs(rhs))
        max_constraint_violation = max(
            max_constraint_violation, violation / scale
        )

    feasible = not (
        missing
        or non_finite
        or unsupported_senses
        or max_bound_violation > tolerance
        or max_integrality_violation > tolerance
        or max_constraint_violation > tolerance
    )
    return {
        "feasible": feasible,
        "tolerance": tolerance,
        "missing_variables": missing[:20],
        "non_finite_variables": non_finite[:20],
        "unsupported_senses": unsupported_senses[:20],
        "max_bound_violation": max_bound_violation,
        "max_integrality_violation": max_integrality_violation,
        "max_scaled_constraint_violation": max_constraint_violation,
    }


def _finite_bound(value: Any, default: float) -> float:
    if value in (None, ""):
        return float(default)
    return float(value)


def _json_object(text: str) -> Any:
    cleaned = str(text or "").strip()
    if cleaned.startswith("```"):
        first_newline = cleaned.find("\n")
        if first_newline >= 0:
            cleaned = cleaned[first_newline + 1 :]
        if cleaned.rstrip().endswith("```"):
            cleaned = cleaned.rstrip()[:-3].rstrip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start < 0 or end < start:
        return None
    try:
        return json.loads(cleaned[start : end + 1])
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def _heading_code_slots(text: str) -> dict[str, str]:
    matches = list(_SLOT_HEADING.finditer(text))
    slots: dict[str, str] = {}
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        section = text[match.end() : end]
        lines = section.splitlines()
        fence_indexes = [
            line_index
            for line_index, line in enumerate(lines)
            if line.strip().startswith("```")
        ]
        if fence_indexes:
            first = fence_indexes[0] + 1
            last = fence_indexes[-1] if len(fence_indexes) > 1 else len(lines)
            code = "\n".join(lines[first:last])
        else:
            code = section
        code = sanitize_code_slot(code)
        if code:
            slots[match.group(1).lower()] = code
    return slots


def _public_schema_names(public_context: dict[str, Any]) -> set[str]:
    tables = public_context.get("tables") if isinstance(public_context, dict) else {}
    if not isinstance(tables, dict):
        return set()
    names = {str(name) for name in tables}
    for rows in tables.values():
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                names.update(str(key) for key in row)
    return names
