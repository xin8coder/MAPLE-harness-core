from __future__ import annotations

import ast
import builtins
import csv
import copy
import math
import re
import signal
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from evo2.core.artifacts import (
    COMPOSITE_ENCODINGS,
    PERMUTATION_ENCODINGS,
    ArtifactBundle,
    GeneratedArtifact,
    deterministic_genome_from_spec,
)


class ArtifactSandboxError(ValueError):
    pass


_PUBLIC_CSV_ROW_CACHE: dict[tuple[str, str, int, int], list[dict[str, Any]]] = {}


@dataclass
class ArtifactValidationResult:
    success: bool
    errors: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


class ArtifactSandbox:
    """Auditable safe-Python sandbox for LLM-generated optimization artifacts.

    The sandbox is intentionally domain-neutral: it constrains *capabilities*
    rather than problem structure. Generated artifacts may use ordinary local
    Python control flow, standard-library imports, and helper functions, but
    may not import LiveOpt/framework-private modules or call unknown framework
    APIs. Runtime helpers such as load_table/list_tables are injected by the
    sandbox as explicit public capabilities.
    """

    def load_bundle(self, bundle: ArtifactBundle):
        from evo2.core.artifacts import UniversalOptimizationArtifact

        functions = self.load_functions(bundle)
        return UniversalOptimizationArtifact(bundle=bundle, functions=functions)

    def load_functions(self, bundle: ArtifactBundle) -> dict[str, Callable]:
        env = _safe_env()
        functions: dict[str, Callable] = {}
        known_functions = {artifact.function_name for artifact in bundle.artifacts.values()}
        for artifact_type, artifact in bundle.artifacts.items():
            tree = ast.parse(artifact.code)
            visitor = _ArtifactSafetyVisitor(artifact.function_name, known_functions=known_functions)
            visitor.visit(tree)
            if not visitor.has_required:
                raise ArtifactSandboxError(f"{artifact.artifact_id} must define {artifact.function_name}")
            exec(compile(tree, f"<generated_{artifact.artifact_id}>", "exec"), env, env)
            fn = env.get(artifact.function_name)
            if not callable(fn):
                raise ArtifactSandboxError(f"{artifact.artifact_id} must define {artifact.function_name}")
            functions[artifact_type] = fn
        return functions

    def load_function(self, artifact: GeneratedArtifact) -> Callable:
        tree = ast.parse(artifact.code)
        visitor = _ArtifactSafetyVisitor(artifact.function_name)
        visitor.visit(tree)
        if not visitor.has_required:
            raise ArtifactSandboxError(f"{artifact.artifact_id} must define {artifact.function_name}")
        env = _safe_env()
        exec(compile(tree, f"<generated_{artifact.artifact_id}>", "exec"), env, env)
        fn = env.get(artifact.function_name)
        if not callable(fn):
            raise ArtifactSandboxError(f"{artifact.artifact_id} must define {artifact.function_name}")
        return fn

    def __init__(self, validation_timeout_seconds: float = 8.0):
        self.validation_timeout_seconds = validation_timeout_seconds

    def validate_bundle(self, bundle: ArtifactBundle) -> ArtifactValidationResult:
        errors: list[str] = _bundle_contract_errors(bundle)
        try:
            loaded = self.load_functions(bundle)
        except Exception as exc:
            errors.append(f"load_bundle: {exc}")
        if errors:
            return ArtifactValidationResult(False, errors)

        tests = bundle.tests or [{}]
        for idx, case in enumerate(tests):
            try:
                _run_with_timeout(self.validation_timeout_seconds, self._run_case, bundle, loaded, case)
            except Exception as exc:
                errors.append(f"test[{idx}]: {exc}")
        return ArtifactValidationResult(not errors, errors, {"test_count": len(tests), "artifact_count": len(bundle.artifacts)})

    def _run_case(self, bundle: ArtifactBundle, loaded: dict[str, Callable], case: dict[str, Any]) -> None:
        contract = case.get("contract") or bundle.contract.__dict__
        memory = dict(case.get("memory", {}))
        if "precompute" in loaded:
            precomputed = loaded["precompute"](contract, memory)
            if not isinstance(precomputed, dict):
                raise ArtifactSandboxError("precompute must return a dict")
            memory["precomputed"] = precomputed
        solution = copy.deepcopy(case.get("solution"))
        if solution is None and "encoding_spec" in loaded and "decode" in loaded:
            spec = loaded["encoding_spec"](contract, memory)
            genome = deterministic_genome_from_spec(spec if isinstance(spec, dict) else {}, 0)
            solution = loaded["decode"](genome, contract, memory)
            if not isinstance(solution, dict):
                raise ArtifactSandboxError("decode must return a dict solution")
            self._check_solution_schema(solution, contract, "decode")
            self._check_genome_compatible(spec if isinstance(spec, dict) else {}, genome, solution.get("genome"), "decode")
        if solution is None:
            solution = {}
        if "repair_operator" in loaded:
            before_repair_genome = copy.deepcopy(solution.get("genome")) if isinstance(solution, dict) else None
            spec_for_repair = loaded["encoding_spec"](contract, memory) if "encoding_spec" in loaded else {}
            solution = loaded["repair_operator"](solution, contract, memory)
            if isinstance(spec_for_repair, dict) and before_repair_genome is not None and isinstance(solution, dict):
                self._check_genome_compatible(spec_for_repair, before_repair_genome, solution.get("genome"), "repair_operator")
            self._check_solution_schema(solution, contract, "repair_operator")
        verification = loaded["verifier"](solution, contract, memory)
        if not isinstance(verification, dict) or "feasible" not in verification:
            raise ArtifactSandboxError("verifier must return dict with feasible")
        expected = case.get("expected") if isinstance(case.get("expected"), dict) else {}
        allow_infeasible = bool(case.get("allow_infeasible")) or expected.get("feasible") is False
        if verification.get("feasible") is not True and not allow_infeasible:
            violations = verification.get("violations") if isinstance(verification.get("violations"), dict) else {}
            raise ArtifactSandboxError(
                "decode plus repair_operator must produce a verifier-feasible solution for validation cases; "
                f"set allow_infeasible only for explicit negative tests. violations={violations}"
            )
        objective = loaded["objective"](solution, contract, memory)
        self._check_objective_contract(objective, contract)
        self._objective_to_float(objective)
        if "encoding_spec" in loaded:
            self._check_operator_semantics(loaded, contract, memory)

    def _check_operator_semantics(self, loaded: dict[str, Callable], contract: dict[str, Any], memory: dict[str, Any]) -> None:
        spec = loaded["encoding_spec"](contract, memory)
        if not isinstance(spec, dict):
            return
        self._check_supported_encoding(spec)
        genome_a = deterministic_genome_from_spec(spec, 0)
        genome_b = deterministic_genome_from_spec(spec, 1)
        if "mutation_operator" in loaded and len(genome_a) > 1:
            mutated = loaded["mutation_operator"](copy.deepcopy(genome_a), contract, memory)
            if mutated == genome_a:
                raise ArtifactSandboxError("mutation_operator must change nontrivial genomes")
            self._check_genome_compatible(spec, genome_a, mutated, "mutation_operator")
            self._exercise_generated_genome(loaded, mutated, contract, memory, "mutation_operator")
        if "crossover_operator" in loaded and len(genome_a) > 1 and genome_a != genome_b:
            child = loaded["crossover_operator"](copy.deepcopy(genome_a), copy.deepcopy(genome_b), contract, memory)
            if child == genome_a and child == genome_b:
                raise ArtifactSandboxError("crossover_operator must combine non-identical parent genomes")
            self._check_genome_compatible(spec, genome_a, child, "crossover_operator")
            self._exercise_generated_genome(loaded, child, contract, memory, "crossover_operator")

    def _check_genome_compatible(self, spec: dict[str, Any], reference: Any, candidate: Any, source: str) -> None:
        if candidate is None:
            raise ArtifactSandboxError(f"{source} must preserve solution['genome']")
        encoding = str(spec.get("encoding", spec.get("type", ""))).lower()
        segments = spec.get("segments") if isinstance(spec.get("segments"), list) else []
        if encoding in COMPOSITE_ENCODINGS or segments:
            if not isinstance(candidate, dict):
                raise ArtifactSandboxError(f"{source} changed composite genome shape")
            reference_map = reference if isinstance(reference, dict) else {}
            for idx, segment in enumerate(segments):
                if not isinstance(segment, dict):
                    continue
                name = str(segment.get("name") or segment.get("role") or f"segment_{idx}")
                if name not in candidate:
                    raise ArtifactSandboxError(f"{source} missing composite genome segment {name}")
                segment_spec = dict(segment)
                segment_spec["encoding"] = str(segment_spec.get("encoding", segment_spec.get("type", segment_spec.get("primitive", "real_vector"))))
                self._check_genome_compatible(segment_spec, reference_map.get(name), candidate.get(name), f"{source}.{name}")
            return
        if encoding in PERMUTATION_ENCODINGS:
            if not isinstance(candidate, list) or any(isinstance(item, (list, dict, tuple, set)) for item in candidate):
                raise ArtifactSandboxError(f"{source} changed flat permutation genome shape")
            values = spec.get("values")
            if isinstance(values, list) and set(candidate) != set(values):
                raise ArtifactSandboxError(f"{source} returned permutation genome with missing or unknown values")
            if isinstance(reference, list) and any(isinstance(item, (list, dict, tuple, set)) for item in reference) != any(isinstance(item, (list, dict, tuple, set)) for item in candidate):
                raise ArtifactSandboxError(f"{source} changed permutation nesting")
        elif encoding in {"real_vector", "int_vector", "integer_vector", "binary"}:
            if not isinstance(candidate, list):
                raise ArtifactSandboxError(f"{source} changed vector genome shape")
            dimension = int(spec.get("dimension", spec.get("dim", len(reference) if isinstance(reference, list) else len(candidate))) or 0)
            if dimension and len(candidate) != dimension:
                raise ArtifactSandboxError(f"{source} returned vector genome length {len(candidate)} but expected {dimension}")

    def _check_supported_encoding(self, spec: dict[str, Any]) -> None:
        encoding = str(spec.get("encoding", spec.get("type", ""))).lower()
        supported = PERMUTATION_ENCODINGS | {"real_vector", "int_vector", "integer_vector", "binary"} | COMPOSITE_ENCODINGS
        if encoding not in supported:
            raise ArtifactSandboxError(f"unsupported encoding_spec encoding: {encoding}; use order_permutation, real_vector, int_vector, binary, or typed composite segments")
        if encoding in COMPOSITE_ENCODINGS or isinstance(spec.get("segments"), list):
            segments = spec.get("segments") if isinstance(spec.get("segments"), list) else []
            if not segments:
                raise ArtifactSandboxError("composite encoding_spec must declare non-empty segments")
            names: set[str] = set()
            for idx, segment in enumerate(segments):
                if not isinstance(segment, dict):
                    raise ArtifactSandboxError("composite encoding_spec segments must be objects")
                name = str(segment.get("name") or segment.get("role") or f"segment_{idx}")
                if name in names:
                    raise ArtifactSandboxError(f"duplicate composite segment name: {name}")
                names.add(name)
                segment_spec = dict(segment)
                segment_spec["encoding"] = str(segment_spec.get("encoding", segment_spec.get("type", segment_spec.get("primitive", "real_vector"))))
                self._check_supported_encoding(segment_spec)

    def _exercise_generated_genome(
        self,
        loaded: dict[str, Callable],
        genome: Any,
        contract: dict[str, Any],
        memory: dict[str, Any],
        source: str,
    ) -> None:
        if "decode" not in loaded:
            return
        try:
            solution = loaded["decode"](copy.deepcopy(genome), contract, memory)
            if not isinstance(solution, dict):
                raise ArtifactSandboxError(f"{source} decode must return a dict solution")
            solution.setdefault("genome", copy.deepcopy(genome))
            self._check_solution_schema(solution, contract, f"{source} decode")
            if "repair_operator" in loaded:
                solution = loaded["repair_operator"](solution, contract, memory)
                self._check_solution_schema(solution, contract, f"{source} repair_operator")
            verification = loaded["verifier"](solution, contract, memory)
            if not isinstance(verification, dict) or "feasible" not in verification:
                raise ArtifactSandboxError(f"{source} verifier must return dict with feasible")
            objective = loaded["objective"](solution, contract, memory)
            self._check_objective_contract(objective, contract)
            self._objective_to_float(objective)
        except ArtifactSandboxError:
            raise
        except Exception as exc:
            raise ArtifactSandboxError(f"{source} generated genome fails decode/repair/verify/objective: {exc}") from exc

    def _check_solution_schema(self, solution: Any, contract: dict[str, Any], source: str) -> None:
        if not isinstance(solution, dict):
            raise ArtifactSandboxError(f"{source} must return a dict solution")
        schema = contract.get("solution_schema", {}) if isinstance(contract, dict) else {}
        if not isinstance(schema, dict):
            return
        if isinstance(schema.get("required_top_level_fields"), list):
            required = schema.get("required_top_level_fields", [])
        elif schema.get("required_field_scope") == "top_level" or not schema.get("task_type"):
            required = schema.get("required_fields", [])
        else:
            required = ["genome"] if "genome" in (schema.get("required_fields", []) or []) else []
        if not isinstance(required, list):
            return
        missing = [str(field) for field in required if str(field) and str(field) not in solution]
        if missing:
            raise ArtifactSandboxError(f"{source} solution missing required field(s): {', '.join(missing)}")

    def _check_objective_contract(self, objective: Any, contract: dict[str, Any]) -> None:
        if not isinstance(objective, dict):
            return
        names = objective.get("objective_names")
        if names is None:
            return
        if not isinstance(names, list) or any(not str(name).strip() for name in names):
            raise ArtifactSandboxError("objective_names must be a non-empty list of public metric names")
        normalized = [str(name).strip() for name in names]
        forbidden = {"error", "failed", "invalid", "placeholder", "unknown"}
        bad = [name for name in normalized if name.lower() in forbidden]
        if bad:
            raise ArtifactSandboxError("objective_names must not use placeholder/error names: " + ", ".join(bad))
        objective_spec = contract.get("objective", {}) if isinstance(contract, dict) else {}
        declared_terms = objective_spec.get("terms", []) if isinstance(objective_spec, dict) else []
        declared = {
            str(term.get("name")).strip()
            for term in declared_terms
            if isinstance(term, dict) and str(term.get("name", "")).strip()
        }
        if declared:
            undeclared = [name for name in normalized if name not in declared]
            if undeclared:
                raise ArtifactSandboxError("objective_names contain undeclared term(s): " + ", ".join(undeclared))

    def _objective_to_float(self, objective: Any) -> float:
        if isinstance(objective, dict):
            scalar = objective.get("scalar")
            if scalar is None:
                objectives = objective.get("objectives")
                if isinstance(objectives, list):
                    scalar = sum(float(value) for value in objectives)
            if scalar is None:
                raise ArtifactSandboxError("multi-objective objective dict must include scalar or objectives list")
            return float(scalar)
        return float(objective)


def _bundle_contract_errors(bundle: ArtifactBundle) -> list[str]:
    errors: list[str] = []
    recommendation = bundle.solver_recommendation if isinstance(bundle.solver_recommendation, dict) else {}
    primary = str(recommendation.get("primary_solver") or recommendation.get("solver") or "").lower()
    use_lp = primary == "linear_program_solver_v1" or bool(recommendation.get("use_linear_program"))
    if use_lp:
        lp_errors = linear_program_spec_contract_errors(bundle.linear_program_spec)
        if lp_errors:
            errors.append("linear_program_solver_v1 requires complete linear_program_spec: " + "; ".join(lp_errors))
    if "precompute" not in bundle.artifacts:
        for artifact_name in ("verifier", "objective"):
            artifact = bundle.artifacts.get(artifact_name)
            code = str(artifact.code or "") if artifact is not None else ""
            if "precomputed" in code:
                errors.append(
                    f"{artifact_name} reads memory['precomputed'] but the bundle has no precompute artifact; "
                    "generate precompute or call load_table directly from verifier/objective."
                )
    return errors


_FORBIDDEN_GENERATED_IMPORT_ROOTS = {"evo2", "liveopt_interface"}


def _forbidden_generated_import(module_name: str | None) -> str | None:
    if not module_name:
        return None
    root = str(module_name).split(".", 1)[0]
    if root in _FORBIDDEN_GENERATED_IMPORT_ROOTS:
        return root
    return None


def linear_program_spec_contract_errors(spec: Any) -> list[str]:
    """Validate the public LP/MILP artifact shape without assuming a domain."""
    errors: list[str] = []

    def _is_number(value: Any) -> bool:
        return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))

    if not isinstance(spec, dict) or not spec:
        return ["missing explicit LLM-generated linear_program_spec"]

    sense = str(spec.get("sense") or "").lower()
    if sense not in {"minimize", "maximize", "min", "max"}:
        errors.append("sense must be minimize or maximize")

    variables = spec.get("variables")
    if not isinstance(variables, list) or not variables:
        errors.append("variables must be a non-empty list")
        variables = []
    variable_names: set[str] = set()
    valid_var_types = {"binary", "integer", "int", "continuous", "real"}
    for idx, variable in enumerate(variables):
        if not isinstance(variable, dict):
            errors.append(f"variables[{idx}] must be an object")
            continue
        name = str(variable.get("name") or "").strip()
        if not name:
            errors.append(f"variables[{idx}].name is required")
        elif name in variable_names:
            errors.append(f"duplicate variable name: {name}")
        else:
            variable_names.add(name)
        var_type = str(variable.get("type") or "").lower()
        if var_type not in valid_var_types:
            errors.append(f"variables[{idx}].type must be binary, integer, or continuous")
        for bound in ("lb", "ub"):
            if bound in variable and not _is_number(variable.get(bound)):
                errors.append(f"variables[{idx}].{bound} must be numeric")

    objective = spec.get("objective")
    objective_coefficients = objective.get("coefficients") if isinstance(objective, dict) else None
    if not isinstance(objective_coefficients, dict) or not objective_coefficients:
        errors.append("objective.coefficients must be a non-empty numeric dict")
    else:
        for name, coefficient in objective_coefficients.items():
            if not isinstance(name, str) or not name:
                errors.append("objective coefficient names must be non-empty strings")
            elif variable_names and name not in variable_names:
                errors.append(f"objective references unknown variable: {name}")
            if not _is_number(coefficient):
                errors.append(f"objective coefficient for {name} must be numeric")

    constraints = spec.get("constraints")
    if constraints is None:
        constraints = []
    if not isinstance(constraints, list):
        errors.append("constraints must be a list")
        constraints = []
    for idx, constraint in enumerate(constraints):
        if not isinstance(constraint, dict):
            errors.append(f"constraints[{idx}] must be an object")
            continue
        coeffs = constraint.get("coefficients")
        if not isinstance(coeffs, dict):
            errors.append(f"constraints[{idx}].coefficients must be a numeric dict")
        else:
            for name, coefficient in coeffs.items():
                if not isinstance(name, str) or not name:
                    errors.append(f"constraints[{idx}] coefficient names must be non-empty strings")
                elif variable_names and name not in variable_names:
                    errors.append(f"constraints[{idx}] references unknown variable: {name}")
                if not _is_number(coefficient):
                    errors.append(f"constraints[{idx}] coefficient for {name} must be numeric")
        if str(constraint.get("sense") or "") not in {"<=", ">=", "=", "=="}:
            errors.append(f"constraints[{idx}].sense must be <=, >=, or =")
        if not _is_number(constraint.get("rhs")):
            errors.append(f"constraints[{idx}].rhs must be numeric")

    extraction = spec.get("solution_extraction")
    if not isinstance(extraction, dict) or not extraction:
        errors.append("solution_extraction is required")
    elif not str(extraction.get("type") or "").strip():
        errors.append("solution_extraction.type is required")

    return errors


def _safe_builtins() -> dict[str, Any]:
    return dict(builtins.__dict__)


def _run_with_timeout(timeout_seconds: float, fn: Callable, *args, **kwargs):
    if timeout_seconds <= 0 or not hasattr(signal, "SIGALRM"):
        return fn(*args, **kwargs)
    previous_handler = signal.getsignal(signal.SIGALRM)

    def handler(_signum, _frame):
        raise ArtifactSandboxError(f"validation timed out after {timeout_seconds:.1f}s")

    signal.signal(signal.SIGALRM, handler)
    signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        return fn(*args, **kwargs)
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def _safe_env() -> dict[str, Any]:
    return {
        "__builtins__": _safe_builtins(),
        "load_table": _load_table,
        "list_tables": _list_tables,
        "math": math,
    }


def _load_table(table_name: str, contract: dict[str, Any], memory: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Load a public table and merge public dynamic table updates.

    This is the preferred generated-code API. It hides whether the static table
    came from CSV, inline rows, or another public source, and it applies
    contract/memory dynamic rows plus metadata dynamic parameter overlays in
    one place.
    """
    memory = memory or {}
    public_data = contract.get("public_data", {}) if isinstance(contract, dict) else {}
    rows = _load_static_table(table_name, contract)
    updates = []
    updates.extend(_table_updates_for(table_name, public_data.get("dynamic_entities")))
    updates.extend(_table_updates_for(table_name, public_data.get("table_updates")))
    updates.extend(_nested_table_updates_for(table_name, public_data))
    updates.extend(_table_updates_for(table_name, memory.get("dynamic_entities")))
    updates.extend(_table_updates_for(table_name, memory.get("table_updates")))
    precomputed = memory.get("precomputed") if isinstance(memory.get("precomputed"), dict) else {}
    updates.extend(_table_updates_for(table_name, precomputed.get("dynamic_entities")))
    updates.extend(_table_updates_for(table_name, precomputed.get("table_updates")))
    rows = _apply_table_updates(rows, updates, _table_key_fields(table_name, contract))
    rows = _apply_table_column_aliases(table_name, rows)
    rows = _apply_dynamic_parameters(
        table_name,
        rows,
        contract.get("metadata", {}) if isinstance(contract, dict) else {},
        memory,
        _table_key_fields(table_name, contract),
    )
    return rows


def _list_tables(contract: dict[str, Any]) -> dict[str, Any]:
    public_data = contract.get("public_data", {}) if isinstance(contract, dict) else {}
    names = set()
    csv_tables = public_data.get("csv_tables", {})
    tables = public_data.get("tables", {})
    if isinstance(csv_tables, dict):
        names.update(csv_tables)
    if isinstance(tables, dict):
        names.update(tables)
    if isinstance(public_data, dict):
        for key, value in public_data.items():
            if key in {"csv_tables", "tables", "table_updates", "dynamic_entities", "csv_schema", "csv_sample_rows", "csv_row_counts", "table_runtime_contract"}:
                continue
            if isinstance(value, list) and all(isinstance(row, dict) for row in value):
                names.add(str(key))
    schema = public_data.get("csv_schema", {}) if isinstance(public_data.get("csv_schema"), dict) else {}
    sample_rows = public_data.get("csv_sample_rows", {}) if isinstance(public_data.get("csv_sample_rows"), dict) else {}
    row_counts = public_data.get("csv_row_counts", {}) if isinstance(public_data.get("csv_row_counts"), dict) else {}
    inline_table_specs = tables if isinstance(tables, dict) else {}
    return {
        name: {
            "columns": schema.get(name) or (inline_table_specs.get(name, {}).get("columns") if isinstance(inline_table_specs.get(name), dict) else None),
            "sample_rows": sample_rows.get(name, (inline_table_specs.get(name, {}).get("rows", [])[:2] if isinstance(inline_table_specs.get(name), dict) and isinstance(inline_table_specs.get(name, {}).get("rows"), list) else [])),
            "row_count": row_counts.get(
                name,
                len(public_data.get(name, []))
                if isinstance(public_data.get(name), list)
                else len(inline_table_specs.get(name, {}).get("rows", []))
                if isinstance(inline_table_specs.get(name), dict) and isinstance(inline_table_specs.get(name, {}).get("rows"), list)
                else None,
            ),
            "source": "csv" if isinstance(csv_tables, dict) and name in csv_tables else "inline",
        }
        for name in sorted(names)
    }


def _load_static_table(table_name: str, contract: dict[str, Any]) -> list[dict[str, Any]]:
    public_data = contract.get("public_data", {}) if isinstance(contract, dict) else {}
    tables = public_data.get("tables", {}) if isinstance(public_data, dict) else {}
    if isinstance(tables, dict) and table_name in tables:
        value = tables[table_name]
        if isinstance(value, list):
            return [dict(row) for row in value if isinstance(row, dict)]
        if isinstance(value, dict) and isinstance(value.get("rows"), list):
            return [dict(row) for row in value["rows"] if isinstance(row, dict)]
    if isinstance(public_data, dict):
        for key in {table_name, f"{table_name}s", table_name[:-1] if table_name.endswith("s") else table_name}:
            value = public_data.get(key)
            if isinstance(value, list) and all(isinstance(row, dict) for row in value):
                return [dict(row) for row in value]
    csv_tables = public_data.get("csv_tables", {}) if isinstance(public_data, dict) else {}
    if isinstance(csv_tables, dict) and table_name in csv_tables:
        return _load_public_csv_rows(table_name, contract)
    return []


def _apply_table_column_aliases(table_name: str, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Expose prefix-stripped aliases for table-local dynamic fields.

    Dynamic deltas often use explicit names such as ``absence_nurse`` or
    ``machine_id`` while reusable templates may read the local field
    (``nurse``/``id``). Keep both spellings so data patches remain executable
    without benchmark-specific code branches.
    """
    singular = table_name[:-1] if table_name.endswith("s") else table_name
    prefixes = {singular}
    if singular.endswith("ie"):
        prefixes.add(singular[:-2] + "y")
    reverse_id_alias_bases = {
        str(key)[:-3]
        for row in rows
        for key in row
        if str(key).endswith("_id") and len(str(key)) > 3
    }
    output: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        for key, value in list(row.items()):
            key_text = str(key)
            if key_text.endswith("_id") and len(key_text) > 3:
                item.setdefault(key_text[:-3], value)
            elif key_text in reverse_id_alias_bases and _looks_like_public_identifier(value):
                item.setdefault(f"{key_text}_id", value)
            for prefix in prefixes:
                marker = f"{prefix}_"
                if not key_text.startswith(marker):
                    continue
                alias = key_text[len(marker):]
                if alias:
                    item.setdefault(alias, value)
        output.append(item)
    return output


def _looks_like_public_identifier(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text:
        return False
    lowered = text.lower()
    if lowered in {"true", "false", "yes", "no", "active", "inactive", "available", "unavailable"}:
        return False
    return any(ch.isalpha() for ch in text)


def _load_public_csv_rows(table_name: str, contract: dict[str, Any]) -> list[dict[str, Any]]:
    """Read a CSV table explicitly exposed in contract.public_data.csv_tables."""
    public_data = contract.get("public_data", {}) if isinstance(contract, dict) else {}
    csv_tables = public_data.get("csv_tables", {}) if isinstance(public_data, dict) else {}
    table_spec = csv_tables.get(table_name) if isinstance(csv_tables, dict) else None
    if not isinstance(table_spec, dict):
        raise ArtifactSandboxError(f"CSV table is not exposed: {table_name}")
    path = Path(str(table_spec.get("path", ""))).expanduser().resolve()
    allowed_root = table_spec.get("allowed_root") or public_data.get("csv_allowed_root")
    if allowed_root:
        root = Path(str(allowed_root)).expanduser().resolve()
        if root != path and root not in path.parents:
            raise ArtifactSandboxError(f"CSV table path is outside allowed root: {table_name}")
    if not path.exists() or not path.is_file():
        raise ArtifactSandboxError(f"CSV table file does not exist: {table_name}")
    stat = path.stat()
    cache_key = (table_name, str(path), int(stat.st_mtime_ns), int(stat.st_size))
    cached = _PUBLIC_CSV_ROW_CACHE.get(cache_key)
    if cached is not None:
        return [dict(row) for row in cached]
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows.append({key: _coerce_csv_value(value) for key, value in row.items()})
    _PUBLIC_CSV_ROW_CACHE[cache_key] = [dict(row) for row in rows]
    return [dict(row) for row in rows]


def _table_updates_for(table_name: str, data: Any) -> list[dict[str, Any]]:
    if not data:
        return []
    if isinstance(data, dict):
        if isinstance(data.get(table_name), list):
            return [_normalize_table_update(item) for item in data[table_name] if isinstance(item, dict)]
        plural = f"{table_name}s"
        singular = table_name[:-1] if table_name.endswith("s") else table_name
        for key in {plural, singular}:
            if isinstance(data.get(key), list):
                return [_normalize_table_update(item) for item in data[key] if isinstance(item, dict)]
        if isinstance(data.get("table"), str) and data.get("table") == table_name:
            return [_normalize_table_update(data)]
        semantic_updates = _semantic_dynamic_updates_for(table_name, data)
        if semantic_updates:
            return semantic_updates
    if isinstance(data, list):
        updates = []
        for item in data:
            if not isinstance(item, dict):
                continue
            item_table = item.get("table") or item.get("table_name")
            if item_table and item_table != table_name:
                continue
            if not item_table and not _unscoped_update_matches_table(table_name, item):
                continue
            updates.append(_normalize_table_update(item))
        return updates
    return []


def _unscoped_update_matches_table(table_name: str, item: dict[str, Any]) -> bool:
    row = item.get("row") if isinstance(item.get("row"), dict) else item
    if not isinstance(row, dict):
        return False
    table_tokens = _semantic_table_tokens(table_name)
    if not table_tokens:
        return False
    row_tokens: set[str] = set()
    for key in row:
        if key in {"op", "table", "table_name"}:
            continue
        row_tokens.update(_identifier_tokens(key))
    return bool(row_tokens & table_tokens)


def _semantic_dynamic_updates_for(table_name: str, data: dict[str, Any]) -> list[dict[str, Any]]:
    table_tokens = _semantic_table_tokens(table_name)
    if not table_tokens:
        return []
    updates: list[dict[str, Any]] = []
    for raw_key, value in data.items():
        if raw_key in {"table_updates", "dynamic_entities", "csv_tables", "csv_schema", "tables", "table_runtime_contract"}:
            continue
        if not isinstance(value, list):
            continue
        key_tokens = _identifier_tokens(raw_key)
        if not key_tokens or not (key_tokens & table_tokens):
            continue
        for item in value:
            if isinstance(item, dict):
                updates.append(_normalize_table_update(item))
    return updates


def _semantic_table_tokens(table_name: str) -> set[str]:
    return _identifier_tokens(table_name)


def _identifier_tokens(value: Any) -> set[str]:
    text = str(value).strip().lower()
    if not text:
        return set()
    parts = [part for part in re.split(r"[^a-z0-9]+", text) if part]
    tokens = set(parts)
    for part in parts:
        if part.endswith("ies") and len(part) > 3:
            tokens.add(part[:-3] + "y")
        if part.endswith("s") and len(part) > 1:
            tokens.add(part[:-1])
    return tokens


def _nested_table_updates_for(table_name: str, public_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Compatibility for table-local dynamic patches.

    The canonical protocol is top-level public_data.dynamic_entities or
    public_data.table_updates. Some role agents may still place updates under
    public_data.<table>.table_updates while preserving CSV metadata. Treat those
    as first-class updates so dynamic patches remain executable.
    """
    if not isinstance(public_data, dict):
        return []
    candidates = []
    for key in {table_name, f"{table_name}s", table_name[:-1] if table_name.endswith("s") else table_name}:
        value = public_data.get(key)
        if isinstance(value, dict):
            candidates.extend(_table_updates_for(table_name, value.get("dynamic_entities")))
            candidates.extend(_table_updates_for(table_name, value.get("table_updates")))
            if any(k in value for k in {"id", "op", "row", "table", "table_name"}):
                candidates.extend(_table_updates_for(table_name, value))
    csv_tables = public_data.get("csv_tables")
    if isinstance(csv_tables, dict):
        spec = csv_tables.get(table_name)
        if isinstance(spec, dict):
            candidates.extend(_table_updates_for(table_name, spec.get("dynamic_entities")))
            candidates.extend(_table_updates_for(table_name, spec.get("table_updates")))
    return candidates


def _normalize_table_update(item: dict[str, Any]) -> dict[str, Any]:
    if "row" in item and isinstance(item["row"], dict):
        row = dict(item["row"])
    else:
        row = {k: v for k, v in item.items() if k not in {"op", "table", "table_name"}}
    _flatten_nested_id_row(row)
    return {"op": item.get("op", "upsert"), "row": row}


def _flatten_nested_id_row(row: dict[str, Any]) -> None:
    nested_id = row.get("id")
    if not isinstance(nested_id, dict):
        return
    row.pop("id", None)
    for key, value in nested_id.items():
        row.setdefault(str(key), value)


def _apply_dynamic_parameters(
    table_name: str,
    rows: list[dict[str, Any]],
    metadata: Any,
    memory: Any,
    key_fields: list[str] | None = None,
) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    sources = []
    if isinstance(metadata, dict):
        sources.append(metadata.get("dynamic_parameters"))
    if isinstance(memory, dict):
        sources.append(memory.get("dynamic_parameters"))
        memory_metadata = memory.get("metadata")
        if isinstance(memory_metadata, dict):
            sources.append(memory_metadata.get("dynamic_parameters"))
        precomputed = memory.get("precomputed")
        if isinstance(precomputed, dict):
            sources.append(precomputed.get("dynamic_parameters"))
    for source in sources:
        output = _apply_dynamic_parameter_source(table_name, output, source, key_fields)
    return output


def _apply_dynamic_parameter_source(table_name: str, rows: list[dict[str, Any]], params: Any, key_fields: list[str] | None = None) -> list[dict[str, Any]]:
    if not isinstance(params, dict):
        return rows
    output = [dict(row) for row in rows]
    keys = {table_name, f"{table_name}s", table_name[:-1] if table_name.endswith("s") else table_name}
    for key in keys:
        if key in params:
            output = _apply_dynamic_parameter_value(output, params[key])
    output = _apply_dotted_dynamic_parameters(table_name, output, params, key_fields)
    return output


def _apply_dotted_dynamic_parameters(
    table_name: str,
    rows: list[dict[str, Any]],
    params: dict[str, Any],
    key_fields: list[str] | None,
) -> list[dict[str, Any]]:
    """Apply generic table-key parameters such as coverage.D3.night.required_delta.

    The interpretation is data-driven by contract.public_data.table_runtime_contract:
    <table>.<key-value...>.<field> updates a row keyed by the table key fields,
    and a *_delta suffix adds to the current numeric value.
    """
    output = [dict(row) for row in rows]
    if key_fields == []:
        key_fields = []
    for raw_key, raw_value in params.items():
        parts = str(raw_key).split(".")
        if len(parts) < 3 or parts[0] != table_name:
            continue
        field = parts[-1]
        key_values = parts[1:-1]
        if not field or not key_values:
            continue
        if key_fields is None:
            if len(key_values) == 1:
                inferred_keys = ["id"]
            else:
                continue
        else:
            inferred_keys = list(key_fields)
        if len(inferred_keys) != len(key_values):
            continue
        is_delta = field.endswith("_delta")
        target_field = field[:-6] if is_delta else field
        row = {key: value for key, value in zip(inferred_keys, key_values)}
        if is_delta:
            current = _find_matching_row(output, row, inferred_keys)
            base_value = current.get(target_field, 0) if current else 0
            row[target_field] = _numeric_or_default(base_value, 0.0) + _numeric_or_default(raw_value, 0.0)
        else:
            row[target_field] = raw_value
        output = _apply_table_updates(output, [{"op": "upsert", "row": row}], inferred_keys)
    return output


def _find_matching_row(rows: list[dict[str, Any]], key_row: dict[str, Any], key_fields: list[str]) -> dict[str, Any] | None:
    if key_fields == []:
        return rows[0] if rows else None
    for row in rows:
        if not isinstance(row, dict):
            continue
        if all(str(row.get(key)) == str(key_row.get(key)) for key in key_fields):
            return row
    return None


def _numeric_or_default(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return float(default)


def _apply_dynamic_parameter_value(rows: list[dict[str, Any]], value: Any) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    if isinstance(value, list):
        for item in value:
            output = _apply_dynamic_parameter_value(output, item)
        return output
    if not isinstance(value, dict):
        return output
    if any(key in value for key in {"op", "row", "table", "table_name"}):
        return _apply_table_updates(output, [_normalize_table_update(value)])
    if "id" in value and any(key != "id" for key in value):
        return _apply_table_updates(output, [{"op": "upsert", "row": dict(value)}])

    row_ids = {str(row.get("id")) for row in output if isinstance(row, dict) and row.get("id") is not None}
    scalar_fields: dict[str, Any] = {}
    updates: list[dict[str, Any]] = []
    for key, item in value.items():
        if isinstance(item, dict):
            row = dict(item)
            row.setdefault("id", key)
            updates.append({"op": "upsert", "row": row})
        elif str(key) in row_ids:
            updates.append({"op": "upsert", "row": {"id": key, "value": item}})
        else:
            scalar_fields[str(key)] = item
    if updates:
        output = _apply_table_updates(output, updates)
    if scalar_fields:
        if not output:
            output.append(dict(scalar_fields))
        elif len(output) == 1 or not any("id" in row for row in output):
            merged = dict(output[0])
            merged.update(scalar_fields)
            output[0] = merged
        else:
            output = [dict(row, **scalar_fields) for row in output]
    return output


def _table_key_fields(table_name: str, contract: dict[str, Any]) -> list[str] | None:
    public_data = contract.get("public_data", {}) if isinstance(contract, dict) else {}
    runtime_contract = public_data.get("table_runtime_contract") if isinstance(public_data, dict) and isinstance(public_data.get("table_runtime_contract"), dict) else {}
    table_keys = runtime_contract.get("table_keys") if isinstance(runtime_contract.get("table_keys"), dict) else {}
    singletons = runtime_contract.get("singleton_tables") if isinstance(runtime_contract.get("singleton_tables"), list) else []
    if table_name in {str(item) for item in singletons}:
        return []
    if _looks_like_singleton_table_name(table_name, public_data):
        return []
    if table_name in table_keys:
        fields = table_keys.get(table_name)
        if isinstance(fields, list) and fields:
            return [str(item) for item in fields]
        if not isinstance(fields, list):
            return None
        inferred = _infer_table_key_fields_from_public_schema(table_name, public_data)
        if inferred:
            return inferred
        return None
    inferred = _infer_table_key_fields_from_public_schema(table_name, public_data)
    if inferred:
        return inferred
    return None


def _infer_table_key_fields_from_public_schema(table_name: str, public_data: dict[str, Any]) -> list[str] | None:
    columns: list[str] = []
    schema = public_data.get("csv_schema") if isinstance(public_data.get("csv_schema"), dict) else {}
    raw_columns = schema.get(table_name) if isinstance(schema, dict) else None
    if isinstance(raw_columns, list):
        columns = [str(item) for item in raw_columns]
    if not columns:
        tables = public_data.get("tables") if isinstance(public_data.get("tables"), dict) else {}
        rows = tables.get(table_name) if isinstance(tables, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    columns = [str(item) for item in row.keys()]
                    break
    if not columns:
        return None
    colset = set(columns)
    if "id" in colset:
        return ["id"]
    table_named = _table_named_id_key(table_name, columns)
    if table_named:
        return [table_named]
    composite = _semantic_composite_key_fields(columns)
    if composite:
        return composite
    if {"day", "shift"} <= colset:
        return ["day", "shift"]
    if {"source", "target"} <= colset:
        return ["source", "target"]
    id_like = [col for col in columns if col.endswith("_id")]
    if len(id_like) == 1:
        return id_like
    return None


def _semantic_composite_key_fields(columns: list[str]) -> list[str]:
    value_like = {
        "active",
        "available",
        "capacity",
        "cost",
        "demand",
        "due",
        "forbidden",
        "limit",
        "mandatory",
        "preference",
        "priority",
        "ready",
        "required",
        "score",
        "service",
        "value",
        "weight",
        "x",
        "y",
    }
    keys = []
    for column in columns:
        lower = str(column).lower()
        if lower in value_like:
            continue
        if lower.endswith(("_time", "_cost", "_count", "_price", "_weight", "_value", "_factor", "_penalty")):
            continue
        keys.append(str(column))
    if 1 < len(keys) <= 3:
        return keys
    return []


def _table_named_id_key(table_name: str, columns: list[str]) -> str | None:
    lower_to_original = {str(col).lower(): str(col) for col in columns}
    for stem in _table_name_stems(table_name):
        candidate = f"{stem}_id"
        if candidate in lower_to_original:
            return lower_to_original[candidate]
    return None


def _table_name_stems(table_name: str) -> list[str]:
    text = str(table_name).strip().lower()
    stems = [text]
    if text.endswith("ies") and len(text) > 3:
        stems.append(text[:-3] + "y")
    if text.endswith("s") and len(text) > 1:
        stems.append(text[:-1])
    output: list[str] = []
    for stem in stems:
        if stem and stem not in output:
            output.append(stem)
    return output


def _looks_like_singleton_table_name(table_name: str, public_data: dict[str, Any]) -> bool:
    key = str(table_name).strip().lower()
    if not any(token in key for token in ["constraint", "param", "setting", "config", "policy", "global"]):
        return False
    columns: list[str] = []
    schema = public_data.get("csv_schema") if isinstance(public_data.get("csv_schema"), dict) else {}
    raw_columns = schema.get(table_name) if isinstance(schema, dict) else None
    if isinstance(raw_columns, list):
        columns = [str(item) for item in raw_columns]
    if not columns:
        tables = public_data.get("tables") if isinstance(public_data.get("tables"), dict) else {}
        rows = tables.get(table_name) if isinstance(tables, dict) else None
        if isinstance(rows, list):
            for row in rows:
                if isinstance(row, dict):
                    columns = [str(item) for item in row.keys()]
                    break
    if not columns:
        return True
    lowered = {column.lower() for column in columns}
    return "id" not in lowered and not any(column.endswith("_id") for column in lowered)


def _apply_table_updates(rows: list[dict[str, Any]], updates: list[dict[str, Any]], key_fields: list[str] | None = None) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    index = _row_id_index(output)
    for update in updates:
        op = str(update.get("op", "upsert")).lower()
        row = update.get("row", {})
        if not isinstance(row, dict):
            continue
        if key_fields and len(key_fields) == 1 and row.get(key_fields[0]) is None and row.get("id") is not None:
            row = dict(row)
            row[key_fields[0]] = row.get("id")
        if key_fields and len(key_fields) == 1 and row.get(key_fields[0]) is None:
            row = _fill_single_key_field_from_alias(row, key_fields[0])
        if key_fields and len(key_fields) > 1:
            row = _fill_composite_key_fields_from_id(row, key_fields)
        row_id = row.get("id")
        row_index = _update_row_index(output, row, row_id, index, key_fields)
        if op in {"delete", "remove"}:
            if row_index is not None:
                output.pop(row_index)
                index = _row_id_index(output)
            continue
        if row_index is not None:
            merged = _merge_update_row(dict(output[row_index]), row)
            output[row_index] = merged
        else:
            output.append(_row_with_delta_fields(row))
            if _is_hashable(row_id):
                index[row_id] = len(output) - 1
    return output


def _fill_single_key_field_from_alias(row: dict[str, Any], key_field: str) -> dict[str, Any]:
    if row.get(key_field) not in (None, ""):
        return row
    alias_keys = [
        key
        for key, value in row.items()
        if key not in {"op", "operation", "table", "table_name", "row"}
        and str(key).endswith("_id")
        and value not in (None, "")
    ]
    if key_field == "id" and len(alias_keys) == 1:
        out = dict(row)
        out[key_field] = row[alias_keys[0]]
        return out
    return row


def _fill_composite_key_fields_from_id(row: dict[str, Any], key_fields: list[str]) -> dict[str, Any]:
    if not key_fields or len(key_fields) <= 1:
        return row
    missing = [field for field in key_fields if row.get(field) in (None, "")]
    raw_id = row.get("id")
    if len(missing) == 1 and raw_id not in (None, ""):
        out = dict(row)
        out.setdefault(missing[0], raw_id)
        return out
    if len(missing) != len(key_fields):
        return row
    if raw_id in (None, ""):
        return row
    parts = [part for part in re.split(r"[^A-Za-z0-9]+", str(raw_id)) if part]
    if len(parts) < len(key_fields):
        return row
    values = parts[-len(key_fields):]
    out = dict(row)
    for field, value in zip(key_fields, values):
        out.setdefault(field, value)
    return out


def _merge_update_row(base: dict[str, Any], row: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in row.items():
        text = str(key)
        if text.endswith("_delta") and len(text) > len("_delta"):
            target = text[: -len("_delta")]
            merged[target] = _numeric_or_default(merged.get(target, 0.0), 0.0) + _numeric_or_default(value, 0.0)
            continue
        if text.endswith("_increase") and len(text) > len("_increase"):
            target = text[: -len("_increase")]
            merged[target] = _numeric_or_default(merged.get(target, 0.0), 0.0) + _numeric_or_default(value, 0.0)
            continue
        if text.endswith("_decrease") and len(text) > len("_decrease"):
            target = text[: -len("_decrease")]
            merged[target] = _numeric_or_default(merged.get(target, 0.0), 0.0) - _numeric_or_default(value, 0.0)
            continue
        if _looks_like_invalid_negative_weight_update(text, value, merged.get(key)):
            raise ArtifactSandboxError(
                f"negative absolute weight update for {text!r}; use {text}_delta for relative changes "
                "or provide the final non-negative weight"
            )
        merged[key] = value
    return merged


def _row_with_delta_fields(row: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in row.items():
        text = str(key)
        if text.endswith("_delta") and len(text) > len("_delta"):
            output[text[: -len("_delta")]] = _numeric_or_default(value, 0.0)
            continue
        if text.endswith("_increase") and len(text) > len("_increase"):
            output[text[: -len("_increase")]] = _numeric_or_default(value, 0.0)
            continue
        if text.endswith("_decrease") and len(text) > len("_decrease"):
            output[text[: -len("_decrease")]] = -_numeric_or_default(value, 0.0)
            continue
        if _looks_like_invalid_negative_weight_update(text, value, None):
            raise ArtifactSandboxError(
                f"negative absolute weight update for {text!r}; use {text}_delta for relative changes "
                "or provide the final non-negative weight"
            )
        output[key] = value
    return output


def _looks_like_invalid_negative_weight_update(field: str, value: Any, current: Any) -> bool:
    if not str(field).endswith("_weight"):
        return False
    try:
        numeric = float(value)
    except Exception:
        return False
    if numeric >= 0:
        return False
    if current in (None, ""):
        return True
    try:
        return float(current) >= 0
    except Exception:
        return True


def _row_id_index(rows: list[dict[str, Any]]) -> dict[Any, int]:
    index: dict[Any, int] = {}
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        row_id = row.get("id")
        if _is_hashable(row_id):
            index[row_id] = idx
    return index


def _is_hashable(value: Any) -> bool:
    if value is None:
        return False
    try:
        hash(value)
    except TypeError:
        return False
    return True


def _update_row_index(
    rows: list[dict[str, Any]],
    update_row: dict[str, Any],
    row_id: Any,
    id_index: dict[Any, int],
    key_fields: list[str] | None,
) -> int | None:
    if key_fields == []:
        return 0 if rows else None
    if key_fields:
        matches = []
        for idx, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            if all(str(row.get(key)) == str(update_row.get(key)) for key in key_fields):
                matches.append(idx)
        return matches[0] if len(matches) == 1 else None
    if row_id is not None:
        indexed = id_index.get(row_id)
        if indexed is not None:
            return indexed
        if _looks_like_singleton_row_index(rows, row_id):
            return 0
        return None
    inferred = _infer_keyless_update_index(rows, update_row)
    if inferred is not None:
        return inferred
    if _looks_like_singleton_parameter_update(rows, update_row):
        return 0
    return None


def _infer_keyless_update_index(rows: list[dict[str, Any]], update_row: dict[str, Any]) -> int | None:
    """Infer a composite-key upsert target for public tables without an id column.

    Several benchmark tables are naturally keyed by fields such as
    (day, shift) or (source, target). Dynamic updates should replace those rows
    rather than append duplicates. We infer the key only when non-numeric,
    identifier-like fields uniquely match one existing row; ambiguous updates
    still append, preserving the conservative generic behavior.
    """
    key_fields = [
        key
        for key, value in update_row.items()
        if key not in {"op", "operation", "table", "table_name", "row"}
        and _looks_like_key_value(value)
    ]
    if not key_fields:
        return None
    matches = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            continue
        if all(str(row.get(key)) == str(update_row.get(key)) for key in key_fields):
            matches.append(idx)
    return matches[0] if len(matches) == 1 else None


def _looks_like_key_value(value: Any) -> bool:
    if value is None or value == "":
        return False
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return False
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return False
        try:
            float(text)
            return False
        except ValueError:
            return True
    return False


def _looks_like_singleton_parameter_update(rows: list[dict[str, Any]], update_row: dict[str, Any]) -> bool:
    if len(rows) != 1 or not isinstance(rows[0], dict):
        return False
    if update_row.get("id") not in (None, ""):
        return False
    ignored = {"op", "operation", "table", "table_name", "row"}
    update_keys = {key for key in update_row if key not in ignored}
    if not update_keys:
        return False
    if any(_looks_like_key_field_name(key) and _looks_like_key_value(value) for key, value in update_row.items() if key not in ignored):
        return False
    existing_keys = set(rows[0])
    if update_keys <= existing_keys:
        return True
    return True


def _looks_like_singleton_row_index(rows: list[dict[str, Any]], row_id: Any) -> bool:
    if len(rows) != 1 or not isinstance(rows[0], dict) or rows[0].get("id") not in (None, ""):
        return False
    return str(row_id).strip().lower() in {"0", "row0", "default", "singleton"}


def _looks_like_key_field_name(key: Any) -> bool:
    text = str(key).lower()
    return text == "id" or text.endswith("_id") or text in {
        "day",
        "shift",
        "nurse",
        "machine",
        "job",
        "operation",
        "source",
        "target",
        "customer",
        "facility",
        "item",
        "order",
        "vehicle",
        "resource",
        "slot",
    }


def _coerce_csv_value(value: Any) -> Any:
    if value is None:
        return None
    text = str(value).strip()
    if text == "":
        return ""
    lowered = text.lower()
    if lowered == "true":
        return True
    if lowered == "false":
        return False
    try:
        if "." not in text and "e" not in lowered:
            return int(text)
        return float(text)
    except ValueError:
        return text


class _ArtifactSafetyVisitor(ast.NodeVisitor):
    """Generated-code checker for the public artifact runtime boundary."""

    def __init__(self, required_function: str, known_functions: set[str] | None = None):
        self.required_function = required_function
        self.has_required = False
        self.known_functions = known_functions or set()
        self.defined_functions: set[str] = set()

    def visit_Module(self, node: ast.Module):
        self.defined_functions = {
            item.name
            for item in ast.walk(node)
            if isinstance(item, ast.FunctionDef) and not item.name.startswith("__")
        }
        self.generic_visit(node)

    def visit_FunctionDef(self, node: ast.FunctionDef):
        if node.name == self.required_function:
            self.has_required = True
        self.generic_visit(node)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            forbidden = _forbidden_generated_import(alias.name)
            if forbidden:
                raise ArtifactSandboxError(
                    f"generated code imports forbidden framework module {forbidden}; "
                    "use sandbox-injected load_table/list_tables and standalone artifact code"
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.level:
            raise ArtifactSandboxError(
                "generated code imports relative/sibling modules; use memory.get('precomputed', {}) instead"
            )
        forbidden = _forbidden_generated_import(node.module)
        if forbidden:
            raise ArtifactSandboxError(
                f"generated code imports forbidden framework module {forbidden}; "
                "use sandbox-injected load_table/list_tables and standalone artifact code"
            )
        self.generic_visit(node)
