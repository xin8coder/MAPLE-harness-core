from __future__ import annotations

import ast
import copy
import math
import random
import time
from dataclasses import dataclass, field, replace
from typing import Any, Callable

from evo2.agents.code_slots import parse_code_slots
from evo2.agents.llm_client import create_llm_client, is_llm_quota_limit_error
from evo2.agents.liveopt_workbench_protocol import build_scaffold_prompt
from evo2.backends.linear_programming_backend import LinearProgrammingBackend
from evo2.core.template_optimizer import (
    Candidate,
    EvolutionConfig,
    EvolutionResult,
    FitnessResult,
    SegmentSpec,
    coerce_fitness_result,
    random_genome,
    run_evolution,
    run_exact_enumeration,
    violation_amount,
)
from evo2.skills.solver.linear_programming_solver import solution_from_linear_program_spec
from evo2.templates.fitness_template import penalty_result


@dataclass
class ScaffoldTrace:
    model: str
    prompts: list[str] = field(default_factory=list)
    raw_responses: list[str] = field(default_factory=list)
    usage: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    latency_seconds: float = 0.0


@dataclass
class ScaffoldProject:
    task_id: str
    data: dict[str, Any]
    segments: list[SegmentSpec]
    setup_code: str
    fitness_code: str
    evaluate: Callable[[dict[str, Any], dict[str, Any]], Any]
    problem_spec: dict[str, Any]
    trace: ScaffoldTrace

    def run(
        self,
        config: EvolutionConfig | None = None,
        data: dict[str, Any] | None = None,
        *,
        initial_genomes: list[dict[str, Any]] | None = None,
    ) -> EvolutionResult:
        cfg = config or EvolutionConfig()
        mode = _solver_mode(self.problem_spec)
        if mode == "linear_mip":
            result = _run_linear_program_project(self.problem_spec, cfg)
            _validate_evolution_result_public_ids(result)
            return result
        if mode == "exact_enumeration":
            cfg = replace(cfg, selection_mode="scalar_ga")
            result = run_exact_enumeration(
                self.segments,
                self.evaluate,
                data=data or self.data,
                config=cfg,
                max_candidates=_exact_candidate_limit(self.problem_spec, cfg),
            )
            _validate_evolution_result_public_ids(result)
            return result
        if mode == "scalar_ga":
            cfg = replace(cfg, selection_mode="scalar_ga")
        elif mode == "moea":
            cfg = replace(cfg, selection_mode="moea")
        if mode not in {"auto", "scalar_ga", "moea", "evolution"}:
            raise ValueError(f"unsupported solver_mode: {mode}")
        result = run_evolution(
            self.segments,
            self.evaluate,
            data=data or self.data,
            config=cfg,
            initial_genomes=initial_genomes,
        )
        _validate_evolution_result_public_ids(result)
        return result


class LiveOptWorkbenchGenerator:
    """One-call generator for LiveOpt Workbench slots.

    The LLM fills only setup.py and fitness.py. The framework owns the main
    loop and all evolutionary operators.
    """

    prompt_version = "liveopt_workbench_v1"

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)
        self.last_trace = ScaffoldTrace(model=model)

    def generate_project(
        self,
        task_id: str,
        natural_language_problem: str,
        public_context: dict[str, Any] | None = None,
        *,
        skill_summary: str = "",
        smoke_test: bool = True,
        max_repairs: int = 3,
    ) -> ScaffoldProject:
        started = time.perf_counter()
        trace = ScaffoldTrace(model=self.model)
        normalized_context = normalize_scaffold_public_context(public_context or {})
        previous_error = ""
        previous_slots: dict[str, str] = {}
        for attempt in range(max(1, int(max_repairs) + 1)):
            prompt = build_scaffold_prompt(
                natural_language_problem,
                normalized_context,
                skill_summary,
                previous_error=previous_error,
                previous_slots=previous_slots,
            )
            try:
                raw = self._chat_text(prompt, trace)
                slots = parse_code_slots(raw)
                previous_slots = dict(slots)
                project = compile_scaffold_project(task_id, normalized_context, slots, trace)
                if smoke_test:
                    project.run(EvolutionConfig(population_size=6, generations=1, seed=0, archive_limit=6))
                trace.latency_seconds = time.perf_counter() - started
                project.trace = trace
                self.last_trace = trace
                return project
            except Exception as exc:  # noqa: BLE001
                if is_llm_quota_limit_error(exc):
                    raise
                previous_error = f"{type(exc).__name__}: {exc}"
                trace.errors.append(previous_error)
                if attempt >= max_repairs:
                    trace.latency_seconds = time.perf_counter() - started
                    self.last_trace = trace
                    raise ValueError("Workbench generation repair failed: " + previous_error) from exc
        raise ValueError("Workbench generation repair failed without producing a project")

    def _chat_text(self, prompt: str, trace: ScaffoldTrace) -> str:
        trace.prompts.append(prompt)
        response = self.client.chat(
            [
                {
                    "role": "system",
                    "content": "You fill setup.py and fitness.py slots for a fixed LiveOpt Workbench. Return only requested code blocks.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=5000,
        )
        trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
        content = response.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(response, dict) else ""
        trace.raw_responses.append(content)
        if not isinstance(content, str) or not content.strip():
            raise ValueError("empty Workbench generator response")
        return content.strip()


def compile_scaffold_project(
    task_id: str,
    public_context: dict[str, Any],
    slots: dict[str, str],
    trace: ScaffoldTrace | None = None,
) -> ScaffoldProject:
    missing = [name for name in ("setup.py", "fitness.py") if name not in slots or not slots[name].strip()]
    if missing:
        raise ValueError("missing Workbench code slots: " + ", ".join(missing))
    public_context = normalize_scaffold_public_context(public_context)
    build_problem = _compile_slot(slots["setup.py"], "build_problem")
    evaluate = _compile_slot(slots["fitness.py"], "evaluate")
    problem_spec = build_problem(copy.deepcopy(public_context))
    if not isinstance(problem_spec, dict):
        raise ValueError("build_problem(public_context) must return a dict")
    data = problem_spec.get("data")
    if not isinstance(data, dict):
        raise ValueError("build_problem result must include data: dict")
    mode = _solver_mode(problem_spec)
    # Exact LP/MILP projects are solved from linear_program_spec; evolutionary
    # chromosome segments are irrelevant there. Some models still emit a
    # placeholder segment while building the exact model, so ignore segments in
    # linear_mip mode instead of letting an unused placeholder fail compilation.
    segments = [] if mode == "linear_mip" else _coerce_segments(problem_spec.get("segments", []))
    if not segments and mode != "linear_mip":
        raise ValueError("build_problem result must include at least one search segment")
    _validate_scaffold_public_contract(
        problem_spec=problem_spec,
        public_context=public_context,
        evaluate=evaluate,
        data=data,
        segments=segments,
        setup_code=slots["setup.py"],
        fitness_code=slots["fitness.py"],
    )
    return ScaffoldProject(
        task_id=task_id,
        data=data,
        segments=segments,
        setup_code=slots["setup.py"],
        fitness_code=slots["fitness.py"],
        evaluate=evaluate,
        problem_spec=dict(problem_spec),
        trace=trace or ScaffoldTrace(model="compiled"),
    )


def normalize_scaffold_public_context(public_context: dict[str, Any]) -> dict[str, Any]:
    """Expose a stable public_context['tables'] ABI to generated Workbench code."""
    context = copy.deepcopy(public_context)
    tables = context.get("tables")
    if tables is None and isinstance(context.get("public_data"), dict):
        public_data = context["public_data"]
        tables = public_data.get("tables") if isinstance(public_data.get("tables"), dict) else public_data
    if tables is None:
        tables = {}
    if not isinstance(tables, dict):
        raise ValueError("public_context['tables'] must be a mapping of table names to rows")
    context["tables"] = {str(name): _normalize_scaffold_table(value) for name, value in tables.items()}
    return context


def _normalize_scaffold_table(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict) and isinstance(value.get("rows"), list):
        value = value["rows"]
    if isinstance(value, dict):
        value = [value]
    if not isinstance(value, list):
        value = [{"value": value}]
    rows: list[dict[str, Any]] = []
    for row in value:
        rows.append(dict(row) if isinstance(row, dict) else {"value": row})
    return rows


def _coerce_segments(raw: Any) -> list[SegmentSpec]:
    if not isinstance(raw, list):
        raise ValueError("segments must be a list")
    return [_coerce_segment(item) for item in raw]


def _coerce_segment(item: Any) -> SegmentSpec:
    if isinstance(item, SegmentSpec):
        return item
    if not isinstance(item, dict):
        raise ValueError(f"segment must be a dict, got {type(item).__name__}")
    kind = str(item.get("kind") or item.get("type") or "").strip()
    name = str(item.get("name") or "").strip()
    if kind in {"assignment", "optional_assignment"}:
        return SegmentSpec(
            name=name,
            kind=kind,
            demands=list(item.get("demands") or item.get("tasks") or item.get("items") or []),
            resources=list(item.get("resources") or item.get("workers") or item.get("options") or []),
            allow_none=bool(item.get("allow_none", kind == "optional_assignment")),
            metadata=_metadata(item),
        )
    if kind == "permutation":
        return SegmentSpec(name=name, kind=kind, values=list(item.get("values") or item.get("items") or []), metadata=_metadata(item))
    if kind == "choice_vector":
        return SegmentSpec(
            name=name,
            kind=kind,
            length=int(item.get("length") or len(item.get("items") or [])),
            options=list(item.get("options") or item.get("choices") or item.get("resources") or []),
            metadata=_metadata(item),
        )
    return SegmentSpec(
        name=name,
        kind=kind,
        length=int(item.get("length") or item.get("dimension") or item.get("dim") or 0),
        lower=item.get("lower", item.get("lb", 0)),
        upper=item.get("upper", item.get("ub", 1)),
        metadata=_metadata(item),
    )


def _metadata(item: dict[str, Any]) -> dict[str, Any]:
    structural = {
        "name",
        "kind",
        "type",
        "demands",
        "tasks",
        "items",
        "resources",
        "workers",
        "options",
        "choices",
        "values",
        "length",
        "dimension",
        "dim",
        "lower",
        "upper",
        "lb",
        "ub",
        "allow_none",
        "metadata",
    }
    metadata: dict[str, Any] = {}
    if isinstance(item.get("metadata"), dict):
        metadata.update(item["metadata"])
    metadata.update({key: value for key, value in item.items() if key not in structural})
    return metadata


def _solver_mode(problem_spec: dict[str, Any]) -> str:
    raw = problem_spec.get("solver_mode")
    if raw is None and isinstance(problem_spec.get("solver"), dict):
        raw = problem_spec["solver"].get("mode")
    mode = str(raw or "auto").strip().lower().replace("-", "_")
    aliases = {
        "": "auto",
        "lp": "linear_mip",
        "milp": "linear_mip",
        "mip": "linear_mip",
        "linear_program": "linear_mip",
        "linear_programming": "linear_mip",
        "linear_program_solver": "linear_mip",
        "linear_program_solver_v1": "linear_mip",
        "linear_milp": "linear_mip",
        "ga": "scalar_ga",
        "single_objective_ga": "scalar_ga",
        "scalar": "scalar_ga",
        "nsga": "moea",
        "nsga_ii": "moea",
        "nsga2": "moea",
        "multi_objective": "moea",
        "exact": "exact_enumeration",
        "enumeration": "exact_enumeration",
        "enumeration_solver": "exact_enumeration",
        "exhaustive": "exact_enumeration",
    }
    return aliases.get(mode, mode)


def _validate_scaffold_public_contract(
    *,
    problem_spec: dict[str, Any],
    public_context: dict[str, Any],
    evaluate: Callable[[dict[str, Any], dict[str, Any]], Any],
    data: dict[str, Any],
    segments: list[SegmentSpec],
    setup_code: str,
    fitness_code: str,
) -> None:
    contract = public_context.get("optimization_contract") if isinstance(public_context, dict) else None
    if not isinstance(contract, dict):
        return
    mode = _solver_mode(problem_spec)
    required_solver_mode = str(contract.get("required_solver_mode") or "").strip().lower()
    if required_solver_mode in {"linear_mip", "linear_mip_when_representable"} and mode != "linear_mip":
        raise ValueError(
            "public exact solver contract requires solver_mode='linear_mip' with a complete linear_program_spec, "
            f"got {problem_spec.get('solver_mode')!r}"
        )
    if contract.get("objective_mode") == "multi_objective":
        expected_names = [str(item) for item in contract.get("objective_names", []) if str(item)]
        if not expected_names:
            raise ValueError("multi_objective public contract requires non-empty objective_names")
        if mode != "moea":
            raise ValueError(
                "public multi_objective contract requires solver_mode='moea', "
                f"got {problem_spec.get('solver_mode')!r}"
            )
        actual_names = [str(item) for item in problem_spec.get("objective_names", []) if str(item)]
        if actual_names != expected_names:
            raise ValueError(
                "public multi_objective contract requires objective_names exactly "
                f"{expected_names!r}, got {actual_names!r}"
            )
        constant_positions = _constant_objective_literal_positions(fitness_code)
        if constant_positions:
            raise ValueError(
                "public multi_objective contract forbids literal constant objective dimensions "
                f"at positions {constant_positions}; compute every Pareto objective from public data and the genome"
            )
        if segments:
            _probe_multiobjective_evaluator(
                evaluate=evaluate,
                data=data,
                segments=segments,
                expected_dim=len(expected_names),
            )
    required_diagnostics = _required_contract_diagnostics(contract)
    if required_diagnostics and segments and mode in {"auto", "scalar_ga", "moea", "evolution"}:
        _validate_search_space_requirements(
            contract=contract,
            public_context=public_context,
            segments=segments,
        )
        _validate_required_public_term_tables(
            contract=contract,
            public_context=public_context,
            setup_code=setup_code,
            fitness_code=fitness_code,
        )
        _validate_optional_field_semantics(
            contract=contract,
            public_context=public_context,
            fitness_code=fitness_code,
        )
        _probe_required_diagnostics(
            evaluate=evaluate,
            data=data,
            segments=segments,
            required_diagnostics=required_diagnostics,
        )


def _constant_objective_literal_positions(code: str) -> list[int]:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    positions: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = node.func.id if isinstance(node.func, ast.Name) else ""
        if func_name != "penalty_result":
            continue
        for keyword in node.keywords:
            if keyword.arg != "objectives":
                continue
            value = keyword.value
            if not isinstance(value, (ast.List, ast.Tuple)):
                continue
            for idx, item in enumerate(value.elts):
                if _is_numeric_literal(item):
                    positions.append(idx)
    return sorted(set(positions))


def _is_numeric_literal(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
        return _is_numeric_literal(node.operand)
    return False


def _probe_multiobjective_evaluator(
    *,
    evaluate: Callable[[dict[str, Any], dict[str, Any]], Any],
    data: dict[str, Any],
    segments: list[SegmentSpec],
    expected_dim: int,
) -> None:
    rng = random.Random(70123)
    probes = [random_genome(segments, rng) for _ in range(max(4, min(8, expected_dim * 3)))]
    for idx, genome in enumerate(probes):
        result = coerce_fitness_result(evaluate(copy.deepcopy(genome), data), genome)
        if len(result.objectives) != expected_dim:
            raise ValueError(
                "public multi_objective contract requires fitness.py to return "
                f"{expected_dim} objective values, probe {idx} returned {len(result.objectives)}"
            )
        if not all(math.isfinite(float(value)) for value in result.objectives):
            raise ValueError(f"public multi_objective contract probe {idx} returned non-finite objectives")
        _validate_solution_public_ids(result.solution)


def _required_contract_diagnostics(contract: dict[str, Any]) -> list[str]:
    required: list[str] = []
    for item in contract.get("required_diagnostics") or []:
        text = str(item).strip()
        if text:
            required.append(text)
    terms = contract.get("objective_terms")
    if isinstance(terms, list):
        for term in terms:
            if not isinstance(term, dict) or not term.get("required_diagnostic"):
                continue
            text = str(term.get("name") or "").strip()
            if text:
                required.append(text)
    seen: set[str] = set()
    out: list[str] = []
    for item in required:
        key = item.lower()
        if key not in seen:
            seen.add(key)
            out.append(item)
    return out


def _probe_required_diagnostics(
    *,
    evaluate: Callable[[dict[str, Any], dict[str, Any]], Any],
    data: dict[str, Any],
    segments: list[SegmentSpec],
    required_diagnostics: list[str],
) -> None:
    rng = random.Random(70124)
    probes = [random_genome(segments, rng) for _ in range(3)]
    required_keys = {str(item) for item in required_diagnostics}
    for idx, genome in enumerate(probes):
        result = coerce_fitness_result(evaluate(copy.deepcopy(genome), data), genome)
        diagnostics = result.diagnostics if isinstance(result.diagnostics, dict) else {}
        missing = [name for name in required_diagnostics if name not in diagnostics]
        if missing:
            raise ValueError(
                "public optimization contract requires fitness.py diagnostics "
                f"{sorted(required_keys)!r}; probe {idx} omitted {missing!r}"
            )
        nonfinite = [
            name
            for name in required_diagnostics
            if not isinstance(diagnostics.get(name), (int, float)) or not math.isfinite(float(diagnostics.get(name)))
        ]
        if nonfinite:
            raise ValueError(
                "public optimization contract requires finite numeric diagnostics; "
                f"probe {idx} returned invalid values for {nonfinite!r}"
            )


def _validate_required_public_term_tables(
    *,
    contract: dict[str, Any],
    public_context: dict[str, Any],
    setup_code: str,
    fitness_code: str,
) -> None:
    terms = contract.get("objective_terms")
    if not isinstance(terms, list):
        return
    tables = public_context.get("tables") if isinstance(public_context.get("tables"), dict) else {}
    available_tables = {str(name) for name in tables}
    combined_code = _strip_python_comments(setup_code + "\n" + fitness_code)
    for term in terms:
        if not isinstance(term, dict):
            continue
        name = str(term.get("name") or "").strip()
        required_tables = [str(item) for item in term.get("required_public_tables") or [] if str(item)]
        required_tables = [table for table in required_tables if table in available_tables]
        if not name or not required_tables:
            continue
        missing = [table for table in required_tables if _code_token_absent(combined_code, table)]
        if missing:
            raise ValueError(
                f"public objective term {name!r} requires reading public table(s) {missing!r}; "
                "do not replace a declared dynamic/public term with a constant or ignore an empty-at-initialization table"
            )
        if _literal_only_assignments(fitness_code, name):
            raise ValueError(
                f"public objective term {name!r} is assigned only literal constants in fitness.py; "
                "compute it from the declared public tables and current candidate solution"
            )


def _validate_optional_field_semantics(
    *,
    contract: dict[str, Any],
    public_context: dict[str, Any],
    fitness_code: str,
) -> None:
    terms = contract.get("objective_terms")
    if not isinstance(terms, list):
        return
    tables = public_context.get("tables") if isinstance(public_context.get("tables"), dict) else {}
    for term in terms:
        if not isinstance(term, dict):
            continue
        term_name = str(term.get("name") or "").strip()
        if not term_name:
            continue
        for rule in term.get("optional_field_semantics") or []:
            if not isinstance(rule, dict) or not rule.get("must_not_gate_term"):
                continue
            table_name = str(rule.get("table") or "")
            field_name = str(rule.get("field") or "")
            rows = tables.get(table_name)
            if not field_name or not isinstance(rows, list):
                continue
            field_visible = any(isinstance(row, dict) and field_name in row for row in rows)
            if field_visible:
                continue
            if _field_guard_can_drop_term(fitness_code, field_name, term_name):
                raise ValueError(
                    f"public objective term {term_name!r} treats missing optional field {field_name!r} "
                    f"from table {table_name!r} as a required condition; "
                    f"{rule.get('when_missing') or 'apply the row at the coarser visible level'}"
                )


def _field_guard_can_drop_term(code: str, field_name: str, term_name: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not _test_requires_name(node.test, field_name):
            continue
        if _subtree_updates_name(node, term_name):
            return True
    return False


def _test_requires_name(node: ast.AST, name: str) -> bool:
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        return any(_test_requires_name(value, name) for value in node.values)
    if isinstance(node, ast.Name) and node.id == name:
        return True
    if isinstance(node, ast.Compare) and _contains_name(node, name):
        return not _is_none_tolerant_compare(node, name)
    return False


def _contains_name(node: ast.AST, name: str) -> bool:
    return any(isinstance(child, ast.Name) and child.id == name for child in ast.walk(node))


def _is_none_tolerant_compare(node: ast.Compare, name: str) -> bool:
    if not isinstance(node.left, ast.Name) or node.left.id != name:
        return False
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return False
    comparator = node.comparators[0]
    if not isinstance(comparator, ast.Constant) or comparator.value is not None:
        return False
    return isinstance(node.ops[0], (ast.Is, ast.Eq))


def _subtree_updates_name(node: ast.AST, name: str) -> bool:
    for child in ast.walk(node):
        if isinstance(child, ast.AugAssign) and _target_name(child.target) == name:
            return True
        if isinstance(child, (ast.Assign, ast.AnnAssign)):
            targets = child.targets if isinstance(child, ast.Assign) else [child.target]
            if any(_target_name(target) == name for target in targets):
                return True
    return False


def _validate_search_space_requirements(
    *,
    contract: dict[str, Any],
    public_context: dict[str, Any],
    segments: list[SegmentSpec],
) -> None:
    requirements = contract.get("search_space_requirements")
    if not isinstance(requirements, list) or not requirements:
        return
    tables = public_context.get("tables") if isinstance(public_context.get("tables"), dict) else {}
    for requirement in requirements:
        if not isinstance(requirement, dict):
            continue
        allowed = {str(item) for item in requirement.get("allowed_segment_kinds") or [] if str(item)}
        if allowed and not any(segment.kind in allowed for segment in segments):
            raise ValueError(
                "public search-space requirement "
                f"{requirement.get('name')!r} requires one of segment kinds {sorted(allowed)!r}; "
                f"got {[segment.kind for segment in segments]!r}"
            )
        required_metadata = requirement.get("required_segment_metadata")
        if isinstance(required_metadata, dict):
            missing_keys = [
                str(key)
                for key in required_metadata
                if not any(
                    segment.kind in {"assignment", "optional_assignment"}
                    and isinstance(segment.metadata, dict)
                    and str(key) in segment.metadata
                    for segment in segments
                )
            ]
            if missing_keys:
                raise ValueError(
                    "public search-space requirement "
                    f"{requirement.get('name')!r} requires assignment segment metadata key(s) {missing_keys!r}; "
                    "declare reusable metadata such as exclusive_resource_per_group instead of relying on random search"
                )
        minimum = _required_minimum_demands(requirement, tables)
        if minimum <= 0:
            continue
        expressive = False
        for segment in segments:
            if segment.kind in {"assignment", "optional_assignment"} and len(segment.demands) >= minimum:
                expressive = True
            elif segment.kind == "choice_vector" and int(segment.length or 0) >= minimum:
                expressive = True
        if not expressive:
            raise ValueError(
                "public search-space requirement "
                f"{requirement.get('name')!r} needs at least {minimum} per-demand choices; "
                "use assignment/optional_assignment demands or a choice_vector with one decision per demand slot"
            )


def _required_minimum_demands(requirement: dict[str, Any], tables: dict[str, Any]) -> int:
    spec = requirement.get("min_demands_from_table")
    if not isinstance(spec, dict):
        raw = requirement.get("min_demands")
        return int(raw or 0)
    table_name = str(spec.get("table") or "")
    column = str(spec.get("column") or "")
    rows = tables.get(table_name)
    if not isinstance(rows, list) or not column:
        return 0
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            total += max(0, int(float(row.get(column, 0) or 0)))
        except (TypeError, ValueError):
            continue
    return total


def _strip_python_comments(code: str) -> str:
    lines = []
    for line in code.splitlines():
        lines.append(line.split("#", 1)[0])
    return "\n".join(lines)


def _code_token_absent(code: str, token: str) -> bool:
    return token not in code


def _literal_only_assignments(code: str, variable_name: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    literal_assign = False
    nonliteral_assign = False
    augmented = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            if any(_target_name(target) == variable_name for target in node.targets):
                if _is_numeric_literal(node.value):
                    literal_assign = True
                else:
                    nonliteral_assign = True
        elif isinstance(node, ast.AnnAssign):
            if _target_name(node.target) == variable_name:
                if node.value is not None and _is_numeric_literal(node.value):
                    literal_assign = True
                else:
                    nonliteral_assign = True
        elif isinstance(node, ast.AugAssign):
            if _target_name(node.target) == variable_name:
                augmented = True
    return literal_assign and not nonliteral_assign and not augmented


def _target_name(target: ast.AST) -> str:
    return target.id if isinstance(target, ast.Name) else ""


_PUBLIC_ID_KEYS = {
    "id",
    "vehicle",
    "vehicle_id",
    "resource",
    "resource_id",
    "machine",
    "machine_id",
    "worker",
    "worker_id",
    "staff",
    "staff_id",
    "order",
    "order_id",
    "task",
    "task_id",
    "job",
    "job_id",
    "item",
    "item_id",
    "customer",
    "customer_id",
    "facility",
    "facility_id",
    "node",
    "node_id",
    "server",
    "server_id",
}


def _validate_evolution_result_public_ids(result: EvolutionResult) -> None:
    candidates = []
    if result.best is not None:
        candidates.append(result.best)
    candidates.extend(result.archive or [])
    seen: set[int] = set()
    for candidate in candidates:
        if id(candidate) in seen or candidate.result is None:
            continue
        seen.add(id(candidate))
        _validate_solution_public_ids(candidate.result.solution)


def _validate_solution_public_ids(value: Any, path: str = "solution") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            normalized_key = str(key).strip().lower()
            if _is_public_identifier_key(normalized_key) and not _is_scalar_public_id(child):
                raise ValueError(
                    f"{child_path} must be a scalar public identifier, not {type(child).__name__}; "
                    "store row details separately and submit only public ids in solution identifiers"
                )
            _validate_solution_public_ids(child, child_path)
    elif isinstance(value, (list, tuple)):
        for idx, child in enumerate(value):
            _validate_solution_public_ids(child, f"{path}[{idx}]")
    elif isinstance(value, set):
        raise ValueError(f"{path} must be JSON-serializable; use a list instead of set")


def _is_public_identifier_key(key: str) -> bool:
    return key in _PUBLIC_ID_KEYS or key.endswith("_id")


def _is_scalar_public_id(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _exact_candidate_limit(problem_spec: dict[str, Any], config: EvolutionConfig) -> int:
    raw = problem_spec.get("max_exact_candidates")
    if raw is None and isinstance(problem_spec.get("solver"), dict):
        raw = problem_spec["solver"].get("max_candidates")
    if raw is None:
        return config.exact_enumeration_limit
    return int(raw)


def _run_linear_program_project(problem_spec: dict[str, Any], config: EvolutionConfig) -> EvolutionResult:
    spec = problem_spec.get("linear_program_spec") or problem_spec.get("lp_spec") or problem_spec.get("milp_spec")
    if not isinstance(spec, dict):
        raise ValueError("solver_mode='linear_mip' requires linear_program_spec")
    result = LinearProgrammingBackend().solve(spec, time_limit=_solver_time_limit(problem_spec))
    if not result.success:
        raise ValueError(f"linear_mip solve failed: status={result.status}; {result.message}")
    solution = solution_from_linear_program_spec(spec, result.variable_values)
    _validate_linear_program_solution(problem_spec, spec, solution)
    scalar = _lp_minimization_scalar(result.objective_value, spec)
    fitness = FitnessResult(
        scalar=scalar,
        objectives=[scalar],
        feasible=True,
        base_scalar=scalar,
        penalty=0.0,
        solution=solution,
        diagnostics={
            "solver_mode": "linear_mip",
            "solver_objective_value": result.objective_value,
            "solver_status": result.status,
            "solver_message": result.message,
            "solver_metadata": result.metadata,
            "raw_solver_values": result.variable_values,
        },
    )
    candidate = Candidate(genome={"solver_values": dict(result.variable_values)}, result=fitness)
    return EvolutionResult(
        best=candidate,
        population=[candidate],
        archive=[candidate],
        history=[
            {
                "generation": 0,
                "feasible": 1,
                "population": 1,
                "best_scalar": scalar,
                "front_size": 0,
                "solver": "linear_mip",
            }
        ],
        metadata={
            "selection": "linear_mip",
            "selection_mode": "linear_mip",
            "population_size": 1,
            "generations": 0,
            "archive_limit": config.archive_limit,
            "solver": result.metadata,
            "solver_status": result.status,
            "solver_objective_value": result.objective_value,
            "variables": len(spec.get("variables", [])),
            "constraints": len(spec.get("constraints", [])),
        },
    )


def _solver_time_limit(problem_spec: dict[str, Any]) -> float | None:
    raw = problem_spec.get("solver_time_limit")
    if raw is None and isinstance(problem_spec.get("solver"), dict):
        raw = problem_spec["solver"].get("time_limit")
    return float(raw) if raw not in (None, "") else None


def _lp_minimization_scalar(objective_value: float | None, spec: dict[str, Any]) -> float:
    value = float(objective_value if objective_value is not None else 0.0)
    sense = str(spec.get("sense", spec.get("objective", {}).get("sense", "minimize"))).lower()
    return -value if sense in {"max", "maximize"} else value


def _validate_linear_program_solution(problem_spec: dict[str, Any], spec: dict[str, Any], solution: dict[str, Any]) -> None:
    extraction = spec.get("solution_extraction") if isinstance(spec.get("solution_extraction"), dict) else {}
    if str(extraction.get("type") or "") != "precedence_schedule":
        return
    assignments = solution.get("assignments") if isinstance(solution.get("assignments"), dict) else {}
    operations = extraction.get("operations") if isinstance(extraction.get("operations"), list) else []
    operation_rows = [item for item in operations if isinstance(item, dict) and item.get("id") not in (None, "")]
    if not operation_rows:
        return
    errors: list[str] = []
    expected_ids = {str(item["id"]) for item in operation_rows}
    if set(assignments) != expected_ids:
        missing = sorted(expected_ids - set(assignments))
        extra = sorted(set(assignments) - expected_ids)
        errors.append(f"operation coverage mismatch missing={missing[:5]!r} extra={extra[:5]!r}")
    intervals: dict[str, list[tuple[float, float, str]]] = {}
    for item in operation_rows:
        op_id = str(item["id"])
        assigned = assignments.get(op_id) if isinstance(assignments.get(op_id), dict) else {}
        machine = assigned.get("machine") or assigned.get("machine_id")
        start = _num_or_none(assigned.get("start", assigned.get("start_time")))
        end = _num_or_none(assigned.get("end", assigned.get("end_time")))
        duration = _num_or_none(item.get("processing_time"))
        if machine in (None, "") or start is None or end is None:
            errors.append(f"{op_id} missing machine/start/end")
            continue
        if duration is not None and end - start < duration - 1e-9:
            errors.append(f"{op_id} duration too short")
        intervals.setdefault(str(machine), []).append((start, end, op_id))
    for machine, rows in intervals.items():
        rows.sort()
        for prev, cur in zip(rows, rows[1:]):
            if cur[0] < prev[1] - 1e-9:
                errors.append(f"machine {machine} overlap {prev[2]}->{cur[2]}")
    for sequence in _job_operation_sequences(problem_spec.get("data")):
        previous_end = None
        previous_op = None
        for op_id in sequence:
            assigned = assignments.get(op_id) if isinstance(assignments.get(op_id), dict) else {}
            start = _num_or_none(assigned.get("start", assigned.get("start_time")))
            end = _num_or_none(assigned.get("end", assigned.get("end_time")))
            if start is None or end is None:
                continue
            if previous_end is not None and start < previous_end - 1e-9:
                errors.append(f"precedence violation {previous_op}->{op_id}")
            previous_end = end
            previous_op = op_id
    if errors:
        raise ValueError("linear_mip precedence_schedule solution violates schedule constraints: " + "; ".join(errors[:6]))


def _job_operation_sequences(data: Any) -> list[list[str]]:
    if not isinstance(data, dict):
        return []
    raw = data.get("job_ops") or data.get("job_operations") or data.get("jobs")
    if isinstance(raw, dict):
        iterable = raw.values()
    elif isinstance(raw, list):
        iterable = raw
    else:
        return []
    sequences: list[list[str]] = []
    for item in iterable:
        ops = item.get("operations") if isinstance(item, dict) else item
        if not isinstance(ops, list):
            continue
        seq = []
        for op in ops:
            if isinstance(op, dict):
                value = op.get("id") or op.get("operation_id") or op.get("op_id")
            else:
                value = op
            if value not in (None, ""):
                seq.append(str(value))
        if seq:
            sequences.append(seq)
    return sequences


def _num_or_none(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _compile_slot(code: str, function_name: str) -> Callable:
    env: dict[str, Any] = {
        "math": math,
        "penalty_result": penalty_result,
        "violation_amount": violation_amount,
        "sum": sum,
        "min": min,
        "max": max,
        "len": len,
        "range": range,
        "enumerate": enumerate,
        "sorted": sorted,
        "isinstance": isinstance,
        "float": float,
        "int": int,
        "str": str,
        "dict": dict,
        "list": list,
        "set": set,
        "tuple": tuple,
        "bool": bool,
        "abs": abs,
        "round": round,
        "zip": zip,
        "any": any,
        "all": all,
    }
    exec(compile(code, f"<scaffold_slot_{function_name}>", "exec"), env, env)
    fn = env.get(function_name)
    if not callable(fn):
        raise ValueError(f"slot must define {function_name}(...)")
    return fn
