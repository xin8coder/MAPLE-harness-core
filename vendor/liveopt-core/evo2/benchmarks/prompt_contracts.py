from __future__ import annotations

import re
from typing import Any


PROMPT_CONTRACT_MARKER = "Public optimization contract:"
UPDATE_CONTRACT_MARKER = "Public update contract:"
LEGACY_PROMPT_CONTRACT_MARKERS = ("Benchmark objective contract:",)
LEGACY_UPDATE_CONTRACT_MARKERS = ("Benchmark update contract:",)


def apply_benchmark_prompt_contract(payload: dict[str, Any]) -> dict[str, Any]:
    """Attach a concise, public objective contract to benchmark NL prompts.

    The contract is prompt-level guidance only. It is derived from public
    evaluation metadata, table schema, and public natural language; it does not
    expose reference solutions or hidden deltas.
    """
    contract = benchmark_prompt_contract(payload)
    if not contract:
        return payload
    metadata = payload.setdefault("metadata", {})
    if isinstance(metadata, dict):
        metadata["benchmark_prompt_contract"] = contract
        public_context = metadata.get("public_context") if isinstance(metadata.get("public_context"), dict) else payload.get("public_context")
        if isinstance(public_context, dict):
            public_context["table_runtime_contract"] = _public_table_runtime_contract(contract)
            solver_profile = contract.get("solver_profile") if isinstance(contract.get("solver_profile"), dict) else {}
            if solver_profile:
                public_context["public_solver_profile"] = solver_profile
            allowed = payload.get("agent_allowed_solvers")
            if isinstance(allowed, list) and allowed:
                public_context["agent_allowed_solvers"] = [str(item) for item in allowed]
            metadata["public_context"] = public_context
    task = str(payload.get("initial_natural_language_task") or payload.get("public_initial_problem") or "")
    task = _compact_table_backed_initial_task(task, payload, contract)
    payload["initial_natural_language_task"] = append_initial_contract(task, contract)
    return payload


def apply_update_prompt_contract(update: dict[str, Any], contract: dict[str, Any] | None) -> dict[str, Any]:
    if not contract:
        return update
    text = str(update.get("natural_language_update") or update.get("public_update") or "")
    update["natural_language_update"] = append_update_contract(text, contract)
    return update


def benchmark_prompt_contract(payload: dict[str, Any]) -> dict[str, Any]:
    evaluation = payload.get("evaluation") if isinstance(payload.get("evaluation"), dict) else {}
    public_context = _public_context(payload)
    declared = _declared_prompt_contract(payload, public_context)
    if declared:
        return _normalize_declared_contract(declared, payload, evaluation, public_context)

    text = str(payload.get("initial_natural_language_task") or payload.get("public_initial_problem") or "")
    objective_definition = _clean_text(evaluation.get("objective_definition"))
    objectives = _infer_objectives(evaluation, public_context, text, objective_definition)
    constraints = _infer_hard_constraints(evaluation, public_context, text)
    diagnostics = _infer_diagnostics(evaluation, objectives, constraints, objective_definition)
    objective_definition = objective_definition or _infer_objective_definition(text, objectives, constraints, public_context)
    objective_definition = _clarify_objective_definition(objective_definition, objectives, public_context)
    if not (objective_definition or objectives or constraints or diagnostics or public_context):
        return {}
    return _contract(
        benchmark_family=_public_profile_id(payload),
        objectives=objectives,
        hard_constraints=constraints,
        diagnostics=diagnostics,
        objective_definition=objective_definition,
        scalarization=_infer_scalarization(evaluation, public_context, objectives, diagnostics, objective_definition),
        table_update_contract=_load_table_contract(public_context),
        solver_profile=_infer_solver_profile(payload, evaluation, public_context),
    )


def append_initial_contract(text: str, contract: dict[str, Any]) -> str:
    if PROMPT_CONTRACT_MARKER in text or any(marker in text for marker in LEGACY_PROMPT_CONTRACT_MARKERS):
        return text
    block = [
        PROMPT_CONTRACT_MARKER,
        f"- Public table/objective profile: {contract.get('benchmark_family')}.",
        f"- Hard feasibility: {_join(contract.get('hard_constraints'))}.",
        f"- Optimized objective terms: {_join(contract.get('objectives'))}.",
        f"- Diagnostics only: {_join(contract.get('diagnostics'))}.",
        f"- Objective definition/scalarization: {contract.get('objective_definition')}. {contract.get('scalarization')}",
        f"- Solver policy: {_solver_policy_prompt(contract.get('solver_profile'))}",
        f"- Public table API: {contract.get('table_update_contract', {}).get('prompt_summary', 'Use load_table(table_name, contract, memory) for public rows and table_updates for data changes.')}",
        "- Use this as a public schema/objective contract, not as a source-specific or instance-specific solver branch.",
        "- Do not introduce additional objective dimensions or treat diagnostics as hard constraints unless a later public update explicitly says so.",
    ]
    return text.rstrip() + "\n\n" + "\n".join(block)


def append_update_contract(text: str, contract: dict[str, Any] | None) -> str:
    if not contract or UPDATE_CONTRACT_MARKER in text or any(marker in text for marker in LEGACY_UPDATE_CONTRACT_MARKERS):
        return text
    block = (
        f"{UPDATE_CONTRACT_MARKER} Keep the public objective/table contract profile '{contract.get('benchmark_family')}' unchanged "
        "unless this public update explicitly changes a listed objective weight, hard constraint, or public table field. "
        "Represent named entity changes as public data/parameter updates; do not add new hidden objectives or source-specific code branches. "
        f"Keep the public solver policy unless this update changes the solver family: {_solver_policy_prompt(contract.get('solver_profile'))} "
        f"Use this public table update policy: {contract.get('table_update_contract', {}).get('prompt_summary', 'load_table plus top-level public_data.table_updates')}."
    )
    return text.rstrip() + "\n\n" + block


def _compact_table_backed_initial_task(text: str, payload: dict[str, Any], contract: dict[str, Any]) -> str:
    """Avoid copying full public table rows into the initial prompt.

    The tables remain available through public_context/load_table; the prompt
    only needs to state the operational task and objective contract.
    """

    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    public_context = metadata.get("public_context") if isinstance(metadata.get("public_context"), dict) else payload.get("public_context")
    if not isinstance(public_context, dict):
        return text
    csv_schema = public_context.get("csv_schema") if isinstance(public_context.get("csv_schema"), dict) else {}
    csv_tables = public_context.get("csv_tables") if isinstance(public_context.get("csv_tables"), dict) else {}
    if not csv_schema and not csv_tables:
        return text
    is_nldo = bool(public_context.get("nldo_problem_id") or public_context.get("nldo_source_id"))
    if len(text) <= 700:
        return text
    table_names = sorted(set(str(x) for x in (csv_schema or csv_tables).keys()))
    family = contract.get("benchmark_family") or payload.get("base_benchmark") or payload.get("benchmark") or "public-table optimization"
    if is_nldo:
        excerpt = _abridge_original_request(text, max_chars=560)
        return (
            f"{excerpt}\n\n"
            "The full instance rows are provided in public tables rather than repeated in the prompt. "
            "Use public_context.csv_schema and load_table(table_name, contract, memory) to inspect rows. "
            f"Public table/objective profile: {family}. Available tables: {_join(table_names)}. "
            "Use the public contract below for the exact optimized terms and hard feasibility conditions."
        )
    return (
        "Instance data is provided in public tables rather than inline prose. "
        "Use public_context.csv_schema and load_table(table_name, contract, memory) to inspect rows. "
        f"Public table/objective profile: {family}. "
        f"Available tables: {_join(table_names)}. "
        "Construct and maintain a feasible optimization solution under later natural-language updates."
    )


def _looks_like_nldo_contract(contract: dict[str, Any]) -> bool:
    family = str(contract.get("benchmark_family") or "").lower()
    return family.startswith("nldo") or "nldo" in family


def _abridge_original_request(text: str, max_chars: int = 560) -> str:
    clean = re.sub(r"\s+", " ", text).strip()
    marker = "Public optimization contract:"
    if marker in clean:
        clean = clean.split(marker, 1)[0].strip()
    if len(clean) <= max_chars:
        return clean
    cut = clean[:max_chars].rsplit(".", 1)[0].strip()
    if len(cut) < max_chars * 0.45:
        cut = clean[:max_chars].rsplit(" ", 1)[0].strip()
    return cut + "."


def _public_context(payload: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    public_context = metadata.get("public_context") if isinstance(metadata.get("public_context"), dict) else payload.get("public_context")
    return public_context if isinstance(public_context, dict) else {}


def _declared_prompt_contract(payload: dict[str, Any], public_context: dict[str, Any]) -> dict[str, Any]:
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    for source in [
        public_context.get("public_optimization_contract"),
        public_context.get("optimization_contract"),
        metadata.get("public_optimization_contract"),
        metadata.get("optimization_contract"),
        metadata.get("benchmark_prompt_contract"),
    ]:
        if isinstance(source, dict):
            return source
    return {}


def _normalize_declared_contract(
    declared: dict[str, Any],
    payload: dict[str, Any],
    evaluation: dict[str, Any],
    public_context: dict[str, Any],
) -> dict[str, Any]:
    text = str(payload.get("initial_natural_language_task") or payload.get("public_initial_problem") or "")
    objective_definition = _clean_text(declared.get("objective_definition") or evaluation.get("objective_definition"))
    objectives = _string_list(declared.get("objectives")) or _infer_objectives(evaluation, public_context, text, objective_definition)
    constraints = _string_list(declared.get("hard_constraints") or declared.get("constraints")) or _infer_hard_constraints(evaluation, public_context, text)
    diagnostics = _string_list(declared.get("diagnostics")) or _infer_diagnostics(evaluation, objectives, constraints, objective_definition)
    table_contract = declared.get("table_update_contract") if isinstance(declared.get("table_update_contract"), dict) else None
    objective_definition = _clarify_objective_definition(
        objective_definition or _infer_objective_definition(text, objectives, constraints, public_context),
        objectives,
        public_context,
    )
    return _contract(
        benchmark_family=str(declared.get("benchmark_family") or declared.get("profile") or _public_profile_id(payload)),
        objectives=objectives,
        hard_constraints=constraints,
        diagnostics=diagnostics,
        objective_definition=objective_definition,
        scalarization=str(declared.get("scalarization") or _infer_scalarization(evaluation, public_context, objectives, diagnostics, objective_definition)),
        table_update_contract=table_contract or _load_table_contract(public_context),
        solver_profile=_infer_solver_profile(payload, evaluation, public_context),
    )


def _public_profile_id(payload: dict[str, Any]) -> str:
    family = _clean_slug(payload.get("family"))
    raw = str(payload.get("episode_id") or payload.get("base_instance_id") or payload.get("source_instance_id") or "")
    raw = re.sub(r"(_slice)?_\d+$", "", raw)
    profile = _clean_slug(raw)
    if profile and family and profile.endswith(f"_{family}"):
        return f"{profile[: -(len(family) + 1)]}:{family}"
    if profile:
        return profile
    for key in ["base_benchmark", "benchmark", "domain", "source_dataset"]:
        profile = _clean_slug(payload.get(key))
        if profile:
            return f"{profile}:{family}" if family and family not in profile else profile
    return "generic_public_benchmark"


def _clean_slug(value: Any) -> str:
    text = _clean_text(value).lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return re.sub(r"_+", "_", text)


def _infer_objectives(
    evaluation: dict[str, Any],
    public_context: dict[str, Any],
    text: str,
    objective_definition: str,
) -> list[str]:
    declared = _string_list(evaluation.get("objectives"))
    if declared:
        return declared
    terms = _objective_terms(objective_definition)
    if terms:
        return ["public_weighted_penalty"] if len(terms) > 4 else terms
    schema = _csv_schema(public_context)
    lower = text.lower()
    if "value" in _all_columns(schema) and any(token in lower for token in ["maximize", "utility", "portfolio"]):
        return ["total_value"]
    if {"open_cost", "capacity"} & _all_columns(schema) and "service" in lower and "cost" in lower:
        return ["opening_and_service_cost"]
    if {"covers", "cost"} <= _all_columns(schema) and ("cover" in lower or "coverage" in lower):
        return ["set_cost"]
    sentence = _objective_sentence_from_text(text)
    if "maximize" in sentence.lower():
        return ["public_utility"]
    if "minimize" in sentence.lower() or "optim" in sentence.lower():
        return ["public_cost"]
    metrics = _string_list(evaluation.get("metrics"))
    ignored = _standard_metric_names() | set(_string_list(evaluation.get("constraints"))) | set(_string_list(evaluation.get("auxiliary_metrics")))
    candidates = [metric for metric in metrics if metric not in ignored and not metric.endswith("_gap")]
    return candidates[:3] if candidates else (["public_objective"] if schema or text else [])


def _infer_hard_constraints(evaluation: dict[str, Any], public_context: dict[str, Any], text: str) -> list[str]:
    constraints = list(_string_list(evaluation.get("constraints")))
    schema = _csv_schema(public_context)
    columns = _all_columns(schema)
    inferred: list[str] = []
    for table, table_columns in schema.items():
        inferred.extend(_table_capacity_constraints(table, table_columns))
    if any(column in {"cpu", "mem", "memory"} or column.endswith("_capacity") for column in columns):
        inferred.append("public resource capacity")
    if "available" in columns or "availability" in columns:
        inferred.append("public availability")
    if "gpu" in columns or "gpu_required" in columns:
        inferred.append("public resource compatibility")
    if "migration_budget" in columns:
        inferred.append("migration_budget")
    lower_text = text.lower()
    if "sla" in lower_text and "diagnostic" not in lower_text and "not hard" not in lower_text:
        inferred.append("sla_feasibility")
    if "active" in columns:
        inferred.append("no inactive or cancelled public rows used")
    if any("eligible" in col for col in columns):
        inferred.append("public eligibility constraints")
    if {"job_id", "sequence_index"} <= columns or {"precedence", "successor"} & columns:
        inferred.append("public precedence/order constraints")
    if {"mandatory", "forbidden"} & columns:
        inferred.append("public mandatory/forbidden constraints")
    if {"covers", "active"} <= columns:
        inferred.append("cover every active public element")
    if "demand" in columns:
        inferred.append("public demand/service requirements")
    if {"required", "day", "shift"} <= columns:
        inferred.append("public coverage requirements")
    if "gpu_required" in columns or "gpu" in columns:
        inferred.append("public resource compatibility")
    if not constraints and not inferred and any(token in text.lower() for token in ["respect", "constraint", "feasible", "capacity"]):
        inferred.append("public feasibility constraints")
    return _merge_unique(constraints, inferred)


def _infer_diagnostics(
    evaluation: dict[str, Any],
    objectives: list[str],
    constraints: list[str],
    objective_definition: str,
) -> list[str]:
    declared = _string_list(evaluation.get("auxiliary_metrics"))
    metrics = _string_list(evaluation.get("metrics"))
    excluded = _standard_metric_names() | {item.lower() for item in objectives} | {item.lower() for item in constraints}
    diagnostics = list(declared)
    for metric in metrics:
        key = metric.lower()
        if key not in excluded and key not in {item.lower() for item in diagnostics}:
            diagnostics.append(metric)
    if objectives == ["public_weighted_penalty"]:
        diagnostics = _merge_unique(diagnostics, _objective_terms(objective_definition))
    return diagnostics


def _infer_objective_definition(
    text: str,
    objectives: list[str],
    constraints: list[str],
    public_context: dict[str, Any],
) -> str:
    sentence = _objective_sentence_from_text(text)
    if sentence:
        return sentence
    sense = _objective_sense(public_context)
    if objectives:
        return f"{sense.capitalize()} {', '.join(objectives)} under public feasibility constraints."
    if constraints:
        return "Construct a feasible solution under the public table constraints."
    return ""


def _infer_scalarization(
    evaluation: dict[str, Any],
    public_context: dict[str, Any],
    objectives: list[str],
    diagnostics: list[str],
    objective_definition: str,
) -> str:
    if _looks_like_formula(objective_definition):
        return f"Use the public objective definition as the deterministic minimization scalar: {objective_definition}; report component diagnostics separately."
    if public_context.get("multi_objective") or len(objectives) > 1:
        return "Use a deterministic minimization scalar for selection while preserving the listed public objective terms for reporting."
    if any("maximize" in str(objective_definition).lower() for _ in [0]):
        return "Expose maximization utilities through an equivalent minimization scalar, and add only public violation or disruption penalties."
    return "Use only the public objective contract for selection and reporting; diagnostics are not new hard constraints."


def _contract(
    benchmark_family: str,
    objectives: list[str],
    hard_constraints: list[str],
    diagnostics: list[str],
    objective_definition: str,
    scalarization: str,
    table_update_contract: dict[str, Any] | None = None,
    solver_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "benchmark_family": benchmark_family,
        "objectives": objectives,
        "hard_constraints": hard_constraints,
        "diagnostics": diagnostics,
        "objective_definition": objective_definition,
        "scalarization": scalarization,
        "table_update_contract": table_update_contract or _load_table_contract({}),
        "solver_profile": solver_profile or {},
        "source": "public_evaluation_fields_and_table_contract",
    }


def _infer_solver_profile(payload: dict[str, Any], evaluation: dict[str, Any], public_context: dict[str, Any]) -> dict[str, Any]:
    allowed = payload.get("agent_allowed_solvers")
    if not isinstance(allowed, list):
        allowed = public_context.get("agent_allowed_solvers") if isinstance(public_context.get("agent_allowed_solvers"), list) else []
    allowed_ids = {str(item) for item in allowed}
    reference_policy = str(evaluation.get("reference_policy") or "").lower()
    reference_rows = evaluation.get("reference_trajectory") if isinstance(evaluation.get("reference_trajectory"), list) else []
    exact_rows = any(str(row.get("reference_type") or "").lower() == "exact_optimum" for row in reference_rows if isinstance(row, dict))
    exact_policy = "exact_optimum" in reference_policy or exact_rows
    if exact_policy and "linear_program_solver_v1" in allowed_ids:
        return {
            "solver_skill_id": "linear_program_solver_v1",
            "policy": "exact_public_table_solver_required",
            "requires_runtime_model_builder": True,
            "reason": "The public benchmark contract declares an exact, linearly representable discrete optimization stage; solve the current public tables with the exact LP/MILP solver skill rather than stochastic search.",
        }
    if allowed_ids:
        return {
            "allowed_solver_skill_ids": sorted(allowed_ids),
            "policy": "choose_from_public_allowed_solvers",
        }
    return {}


def _solver_policy_prompt(profile: Any) -> str:
    if not isinstance(profile, dict) or not profile:
        return "No exact solver requirement is declared; choose a public solver skill from the available generic skills."
    skill_id = profile.get("solver_skill_id")
    policy = profile.get("policy")
    if skill_id:
        return f"{policy}: choose {skill_id}; build the model from current public tables and dynamic table updates, not from hidden references."
    allowed = profile.get("allowed_solver_skill_ids")
    if isinstance(allowed, list) and allowed:
        return f"{policy}: choose among {', '.join(str(item) for item in allowed)} according to the public task structure."
    return str(policy or "public solver policy")


def _load_table_contract(public_context: dict[str, Any]) -> dict[str, Any]:
    public_context = public_context if isinstance(public_context, dict) else {}
    runtime = public_context.get("table_runtime_contract") if isinstance(public_context.get("table_runtime_contract"), dict) else {}
    schema = _csv_schema(public_context)
    common = {
        "load_table_signature": "load_table(table_name: str, contract: dict, memory: dict|None) -> list[dict[str, int|float|bool|str]]",
        "dynamic_update_location": "top-level contract_patch.public_data.table_updates or contract_patch.public_data.dynamic_entities keyed by table name",
        "update_item_schema": {"op": "upsert|delete|remove", "row": "dict of public table fields"},
        "default_upsert": "If a table has id, upsert/delete by id. If the table is declared singleton, replace the one public row. If table_keys are declared, upsert/delete by that composite key.",
        "table_keys": _infer_table_keys(schema),
        "singleton_tables": [],
        "table_operations": {},
    }
    if isinstance(runtime.get("table_keys"), dict):
        common["table_keys"].update({str(k): _string_list(v) for k, v in runtime["table_keys"].items()})
    inferred_singletons = [table for table, keys in common["table_keys"].items() if not keys and _looks_like_singleton_table(table)]
    if isinstance(runtime.get("singleton_tables"), list):
        inferred_singletons.extend(str(item) for item in runtime["singleton_tables"])
    common["singleton_tables"] = sorted(set(inferred_singletons))
    for table, columns in schema.items():
        common["table_operations"][table] = _generic_table_operation(table, columns, common["table_keys"].get(table, []), table in common["singleton_tables"])
    if isinstance(runtime.get("table_operations"), dict):
        common["table_operations"].update({str(k): str(v) for k, v in runtime["table_operations"].items()})
    common["prompt_summary"] = _load_table_prompt_summary(common)
    return common


def _load_table_prompt_summary(contract: dict[str, Any]) -> str:
    parts = [
        "Generated code must call load_table(table_name, contract, memory), which returns list[dict] public rows and merges top-level public_data.table_updates/dynamic_entities.",
    ]
    table_keys = contract.get("table_keys", {}) if isinstance(contract.get("table_keys"), dict) else {}
    if table_keys:
        key_text = ", ".join(f"{table}:({','.join(keys) if keys else 'singleton'})" for table, keys in sorted(table_keys.items()))
        parts.append(f"Table upsert keys: {key_text}.")
    operations = contract.get("table_operations", {}) if isinstance(contract.get("table_operations"), dict) else {}
    if operations:
        parts.append("Use these table operations: " + " ".join(str(value) for _, value in sorted(operations.items())))
    return " ".join(parts)


def _public_table_runtime_contract(contract: dict[str, Any]) -> dict[str, Any]:
    table_update = contract.get("table_update_contract", {}) if isinstance(contract.get("table_update_contract"), dict) else {}
    return {
        "load_table_signature": table_update.get("load_table_signature", "load_table(table_name: str, contract: dict, memory: dict|None) -> list[dict]"),
        "preferred_table_api": "load_table(table_name, contract, memory)",
        "dynamic_update_location": table_update.get("dynamic_update_location", "top-level contract_patch.public_data.table_updates keyed by table name"),
        "update_item_schema": table_update.get("update_item_schema", {"op": "upsert|delete|remove", "row": "dict"}),
        "table_keys": table_update.get("table_keys", {}),
        "singleton_tables": table_update.get("singleton_tables", []),
        "table_operations": table_update.get("table_operations", {}),
        "prompt_summary": table_update.get("prompt_summary", ""),
    }


def _string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item is not None]
    return []


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def _join(value: Any) -> str:
    items = _string_list(value)
    return ", ".join(items) if items else "none"


def _merge_unique(*groups: list[str]) -> list[str]:
    merged: list[str] = []
    seen: set[str] = set()
    for group in groups:
        for raw in group:
            item = _clean_text(raw)
            key = item.lower()
            if item and key not in seen:
                seen.add(key)
                merged.append(item)
    return merged


def _csv_schema(public_context: dict[str, Any]) -> dict[str, list[str]]:
    schema = public_context.get("csv_schema") if isinstance(public_context.get("csv_schema"), dict) else {}
    if schema:
        return {str(table): [str(col) for col in columns] for table, columns in schema.items() if isinstance(columns, list)}
    csv_tables = public_context.get("csv_tables") if isinstance(public_context.get("csv_tables"), dict) else {}
    inferred: dict[str, list[str]] = {}
    for table, spec in csv_tables.items():
        if isinstance(spec, dict) and isinstance(spec.get("columns"), list):
            inferred[str(table)] = [str(col) for col in spec["columns"]]
    return inferred


def _all_columns(schema: dict[str, list[str]]) -> set[str]:
    return {str(col) for columns in schema.values() for col in columns}


def _standard_metric_names() -> set[str]:
    return {
        "feasibility",
        "pareto_coverage",
        "hypervolume",
        "hv",
        "igd",
        "objective_gap",
        "exact_reference_objective",
        "solver_best_known_score",
        "token_cost",
        "latency",
        "latency_seconds",
    }


def _objective_terms(objective_definition: str) -> list[str]:
    if not objective_definition:
        return []
    objective_definition = _strip_diagnostic_clauses(objective_definition)
    stop = {
        "minimize",
        "maximize",
        "optimise",
        "optimize",
        "subject",
        "under",
        "public",
        "constraint",
        "constraints",
        "and",
        "or",
        "plus",
        "minus",
        "the",
        "a",
        "an",
        "use",
        "as",
        "one",
        "scalar",
    }
    terms: list[str] = []
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_]*", objective_definition):
        key = token.lower()
        if key in stop or key in terms:
            continue
        if "_" in token or key.endswith(("cost", "penalty", "shortage", "violation", "violations", "tardiness", "disruption", "distance", "lateness", "emission", "energy", "imbalance", "value", "utility")):
            terms.append(token)
    return terms


def _strip_diagnostic_clauses(text: str) -> str:
    clauses = re.split(r"[.;]", str(text))
    kept: list[str] = []
    for clause in clauses:
        lower = clause.lower()
        if any(token in lower for token in ["diagnostic", "diagnostics", "auxiliary", "reported only", "report only"]):
            continue
        kept.append(clause)
    return "; ".join(kept) if kept else str(text)


def _objective_sentence_from_text(text: str) -> str:
    cleaned = _clean_text(text)
    if not cleaned:
        return ""
    sentences = re.split(r"(?<=[.!?])\s+", cleaned)
    for sentence in sentences:
        lower = sentence.lower()
        if any(token in lower for token in ["minimize", "maximize", "optimise", "optimize"]):
            return sentence[:600]
    return ""


def _objective_sense(public_context: dict[str, Any]) -> str:
    sense = public_context.get("objective_sense")
    if isinstance(sense, str) and sense:
        return sense
    if isinstance(sense, dict) and sense:
        values = {str(item).lower() for item in sense.values()}
        if values == {"maximize"}:
            return "maximize"
    return "minimize"


def _looks_like_formula(text: str) -> bool:
    return bool(text and re.search(r"\b\w+\b\s*[*+/-]\s*(?:\d|\w)", text))


def _clarify_objective_definition(objective_definition: str, objectives: list[str], public_context: dict[str, Any]) -> str:
    text = _clean_text(objective_definition)
    schema = _csv_schema(public_context)
    columns = _all_columns(schema)
    objective_text = " ".join(objectives).lower()
    if "lateness" in objective_text and {"due", "ready"} & columns and "due-time/window overage contributes" not in text.lower():
        text = (
            text.rstrip(".")
            + ". Due-time/window overage contributes to the lateness objective; it is not a hard infeasibility unless a public update explicitly declares a mandatory deadline/window."
        )
    return text


def _table_capacity_constraints(table: str, columns: list[str]) -> list[str]:
    colset = set(columns)
    items: list[str] = []
    if "capacity" in colset:
        items.append("public capacity")
    if "cpu" in colset or "mem" in colset or "memory" in colset:
        items.append("public resource capacity")
    for column in columns:
        if str(column).endswith("_capacity"):
            items.append("public resource capacity")
    return items


def _infer_table_keys(schema: dict[str, list[str]]) -> dict[str, list[str]]:
    return {table: _infer_table_key(table, columns) for table, columns in schema.items()}


def _infer_table_key(table: str, columns: list[str]) -> list[str]:
    names = [str(col) for col in columns]
    colset = set(names)
    if "id" in colset:
        return ["id"]
    table_named = _table_named_id_key(table, names)
    if table_named:
        return [table_named]
    if _looks_like_singleton_table(table):
        return []
    composite = _semantic_composite_key(names)
    if composite:
        return composite
    if {"day", "shift"} <= colset:
        return ["day", "shift"]
    if {"source", "target"} <= colset:
        return ["source", "target"]
    id_like = [col for col in names if col.endswith("_id")]
    if len(id_like) == 1:
        return id_like
    if len(names) <= 3 and names:
        return names[:2]
    return []


def _semantic_composite_key(columns: list[str]) -> list[str]:
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


def _table_named_id_key(table: str, columns: list[str]) -> str | None:
    lower_to_original = {str(col).lower(): str(col) for col in columns}
    for stem in _table_name_stems(table):
        candidate = f"{stem}_id"
        if candidate in lower_to_original:
            return lower_to_original[candidate]
    return None


def _table_name_stems(table: str) -> list[str]:
    text = str(table).strip().lower()
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


def _looks_like_singleton_table(table: str) -> bool:
    key = str(table).lower()
    return any(token in key for token in ["constraint", "param", "setting", "config", "policy", "global"])


def _generic_table_operation(table: str, columns: list[str], keys: list[str], singleton: bool) -> str:
    if singleton:
        return (
            f"{table}: scalar or global changes update the singleton row through public_data.table_updates.{table}. "
            "For objective/penalty weights, provide the final non-negative numeric value. "
            "If the natural-language update is relative and the final value cannot be computed from referenced rows, "
            "use an explicit <field>_delta, <field>_increase, or <field>_decrease field; never encode a signed delta as the bare weight field."
        )
    if keys:
        key_text = ", ".join(keys)
        message = f"{table}: row changes are public_data.table_updates.{table} upserts/deletes keyed by ({key_text}); provide the complete key and do not append another row for the same key."
    else:
        message = f"{table}: row changes are public_data.table_updates.{table} upserts/deletes using the declared public row fields; prefer stable public identifiers when present."
    if "active" in set(columns):
        message += " Use active=false for cancellations or inactive rows when that is the intended public change."
    return message
