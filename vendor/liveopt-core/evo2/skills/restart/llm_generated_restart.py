from __future__ import annotations

import ast
import copy
from typing import Any, Callable

from evo2.core.population import Individual
from evo2.core.solution import Solution
from evo2.skills.base import Skill, SkillContext, SkillResult
from evo2.skills.restart._utils import repair_individual, solution_to_individual


class LLMMemoryFilterRestartSkill(Skill):
    skill_id = "llm_memory_filter_restart_v1"
    skill_type = "restart"
    description = "Use generated scoring logic to filter all historical solutions/populations for the current update."
    suitable_change_scale = "large memory-dependent"
    handles = ["large demand/resource shifts", "many historical candidates", "updates needing selection from previous solutions"]
    limitations = ["requires historical solutions or population", "generated scoring code must stay simple and deterministic"]
    planner_tags = ["memory_filter_code", "large_change", "history_selection"]

    def applicable(self, context: SkillContext) -> bool:
        return bool(context.previous_solution or context.previous_population or context.memory.get("solution_history"))

    def run(self, context: SkillContext) -> SkillResult:
        strategy = context.memory.get("llm_dynamic_strategy", {}) or {}
        code = strategy.get("filter_code") or _default_filter_code()
        scorer = _load_function(code, "score_solution")
        candidates = _collect_all_previous_individuals(context)
        scored = []
        for age, ind in enumerate(candidates):
            features = _solution_features(ind, age)
            try:
                score = float(scorer(features))
            except Exception:
                score = float("inf")
            scored.append((score, age, ind))
        scored.sort(key=lambda x: (x[0], x[1]))
        n = int(context.budget.get("population_size", 24))
        selected = []
        for rank, (_, _, ind) in enumerate(scored[: max(1, n)]):
            item = copy.deepcopy(ind)
            item.individual_id = f"llm_filter_{rank}_{item.individual_id}"
            item.metadata["source"] = "llm_memory_filter_code"
            item.metadata["llm_filter_code"] = code
            selected.append(repair_individual(item, context))
        return SkillResult(True, selected, {"restart": self.skill_id, "count": len(selected), "strategy": strategy})


class LLMRepairOperatorRestartSkill(Skill):
    skill_id = "llm_repair_operator_restart_v1"
    skill_type = "restart"
    description = "Use generated repair logic to modify old solutions before GA search."
    suitable_change_scale = "constraint-focused medium-to-large"
    handles = ["new hard constraints", "infeasible current solution", "resource removal", "time window or eligibility changes"]
    limitations = ["requires previous solution or population", "repair code must be deterministic and safe"]
    planner_tags = ["repair_operator_code", "constraint_change", "infeasibility"]

    def applicable(self, context: SkillContext) -> bool:
        return context.previous_solution is not None or context.previous_population is not None

    def run(self, context: SkillContext) -> SkillResult:
        strategy = context.memory.get("llm_dynamic_strategy", {}) or {}
        code = strategy.get("repair_code") or _default_repair_code()
        repair_fn = _load_function(code, "repair")
        seeds = _collect_all_previous_individuals(context)[: max(1, int(context.budget.get("repair_seed_count", 6)))]
        if not seeds and context.previous_solution is not None:
            seeds = [solution_to_individual(context.previous_solution, "llm_repair_seed")]
        repaired = []
        safe_context = {
            "natural_language_update": context.natural_language_update,
            "patches": [getattr(p, "payload", {}) for p in context.patches],
            "constraints": context.ir.constraints,
            "entities": context.ir.entities,
            "objective": context.ir.objective,
        }
        for idx, ind in enumerate(seeds):
            assignments = copy.deepcopy(ind.solution.assignments)
            try:
                new_assignments = repair_fn(assignments, safe_context)
            except Exception:
                new_assignments = assignments
            sol = Solution(
                solution_id=f"llm_repair_sol_{idx}",
                assignments=new_assignments if isinstance(new_assignments, dict) else assignments,
                metadata={"source": "llm_repair_operator_code", "repair_code": code},
            )
            repaired.append(repair_individual(Individual(f"llm_repair_{idx}", sol, metadata={"source": "llm_repair_operator_code"}), context))
        return SkillResult(True, repaired, {"restart": self.skill_id, "count": len(repaired), "strategy": strategy})


def _collect_all_previous_individuals(context: SkillContext) -> list[Individual]:
    candidates: list[Individual] = []
    if context.previous_population is not None:
        candidates.extend(copy.deepcopy(context.previous_population.individuals))
    if context.previous_solution is not None:
        candidates.append(solution_to_individual(context.previous_solution, "previous_best"))
    for pop in context.memory.get("population_history", []) or []:
        if hasattr(pop, "individuals"):
            candidates.extend(copy.deepcopy(pop.individuals))
    for sol in context.memory.get("solution_history", []) or []:
        if isinstance(sol, dict):
            sol = sol.get("solution")
        if sol is not None and hasattr(sol, "assignments"):
            candidates.append(solution_to_individual(sol, "memory_solution"))
    # Remove exact duplicate assignment signatures while keeping early bests.
    unique = []
    seen = set()
    for ind in candidates:
        sig = repr(sorted((ind.solution.assignments or {}).items()))
        if sig in seen:
            continue
        seen.add(sig)
        unique.append(ind)
    return unique


def _solution_features(ind: Individual, age: int) -> dict[str, Any]:
    sol = ind.solution
    violations = getattr(sol, "violations", {}) or {}
    violation_count = 0
    if isinstance(violations, dict):
        for value in violations.values():
            if isinstance(value, list):
                violation_count += len(value)
            elif value:
                violation_count += 1
    assignments = sol.assignments or {}
    worker_shift = assignments.get("worker_shift", {}) if isinstance(assignments, dict) else {}
    order_slot = assignments.get("order_slot", {}) if isinstance(assignments, dict) else {}
    return {
        "objective_value": sol.objective_value if sol.objective_value is not None else 1e9,
        "feasible": bool(sol.feasible),
        "violation_count": violation_count,
        "age": age,
        "assignment_count": len(worker_shift) + len(order_slot),
        "used_workers": sorted(set(worker_shift.values())) if isinstance(worker_shift, dict) else [],
        "used_slots": sorted(set(order_slot.values())) if isinstance(order_slot, dict) else [],
        "source": ind.metadata.get("source", ""),
    }


def _load_function(code: str, function_name: str) -> Callable:
    tree = ast.parse(code)
    _SafetyVisitor(function_name).visit(tree)
    env = {"__builtins__": {"len": len, "min": min, "max": max, "sum": sum, "float": float, "int": int, "abs": abs, "bool": bool, "sorted": sorted, "set": set, "list": list, "dict": dict, "str": str, "tuple": tuple, "isinstance": isinstance}}
    loc: dict[str, Any] = {}
    exec(compile(tree, "<llm_generated_restart>", "exec"), env, loc)
    fn = loc.get(function_name)
    if not callable(fn):
        raise ValueError(f"generated code must define {function_name}")
    return fn


class _SafetyVisitor(ast.NodeVisitor):
    allowed_nodes = (
        ast.Module, ast.FunctionDef, ast.arguments, ast.arg, ast.Return, ast.Assign, ast.Expr,
        ast.If, ast.For, ast.Load, ast.Store, ast.Name, ast.Constant, ast.Dict, ast.List, ast.Tuple,
        ast.Set, ast.Subscript, ast.Slice, ast.Index, ast.Call, ast.Attribute, ast.Compare, ast.BoolOp,
        ast.BinOp, ast.UnaryOp, ast.IfExp, ast.comprehension, ast.ListComp, ast.SetComp,
        ast.DictComp, ast.keyword, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
        ast.USub, ast.Not, ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt,
        ast.GtE, ast.In, ast.NotIn, ast.Is, ast.IsNot,
    )
    allowed_calls = {"len", "min", "max", "sum", "float", "int", "abs", "bool", "sorted", "set", "list", "dict", "str", "tuple", "isinstance", "get", "copy", "items", "values", "keys"}

    def __init__(self, required_function: str):
        self.required_function = required_function
        self.has_required = False

    def generic_visit(self, node):
        if not isinstance(node, self.allowed_nodes):
            raise ValueError(f"disallowed generated-code node: {type(node).__name__}")
        super().generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name == self.required_function:
            self.has_required = True
        if node.name not in {self.required_function}:
            raise ValueError(f"unexpected function {node.name}")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            name = node.func.id
        elif isinstance(node.func, ast.Attribute):
            name = node.func.attr
        else:
            raise ValueError("disallowed call target")
        if name not in self.allowed_calls:
            raise ValueError(f"disallowed call: {name}")
        self.generic_visit(node)


def _default_filter_code() -> str:
    return "def score_solution(features):\n    return (0 if features.get('feasible') else 1000000) + float(features.get('objective_value') or 0) + 1000*features.get('violation_count', 0) + 0.01*features.get('age', 0)\n"


def _default_repair_code() -> str:
    return "def repair(assignments, context):\n    return assignments\n"
