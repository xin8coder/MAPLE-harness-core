from __future__ import annotations

import copy
from typing import Any


PUBLIC_OBJECTIVE_SPEC_MARKER = "Scoring rules:"
PUBLIC_UPDATE_OBJECTIVE_NOTE_MARKER = "Scoring after this update:"
LEGACY_PUBLIC_OBJECTIVE_SPEC_MARKERS = ("Public objective and scoring specification:",)
LEGACY_PUBLIC_UPDATE_OBJECTIVE_NOTE_MARKERS = ("Public update objective/scoring note:",)


def public_optimization_contract_for_episode(episode: dict[str, Any], benchmark_name: str | None = None) -> dict[str, Any]:
    """Build a public quantitative objective contract for a benchmark episode.

    The contract is profile-level public modeling guidance. It is derived from
    public tables/schema, public objective metadata, and the episode family. It
    intentionally does not include hidden deltas, reference solutions, reference
    objective values, or evaluator implementation details.
    """

    public_context = episode.get("public_context") if isinstance(episode.get("public_context"), dict) else {}
    existing = public_context.get("optimization_contract") or public_context.get("public_optimization_contract")
    if isinstance(existing, dict) and existing.get("version") == "public_quantitative_objective_contract_v1":
        return copy.deepcopy(existing)
    profile = _profile_id(episode, benchmark_name)
    family = _family_id(episode, public_context)
    if profile == "cobench_exact_small" or profile == "cobench":
        return _cobench_contract(family, episode)
    if profile == "fjsp_exact_small" or profile == "fjsp":
        return _fjsp_contract()
    if profile == "inrc_realistic_dynamic" or profile == "inrc2":
        return _inrc_contract()
    if profile == "green_vrp_mo" or profile == "green_vrp_multiobjective":
        return _green_vrp_contract(episode)
    if profile == "cloud_scheduling_mo" or profile == "cloud_scheduling_multiobjective":
        return _cloud_contract(episode)
    return _generic_contract(episode)


def attach_public_optimization_contract(episode: dict[str, Any], benchmark_name: str | None = None) -> dict[str, Any]:
    public_context = copy.deepcopy(episode.get("public_context") if isinstance(episode.get("public_context"), dict) else {})
    contract = public_optimization_contract_for_episode({**episode, "public_context": public_context}, benchmark_name)
    if contract:
        public_spec = public_objective_spec_from_contract(contract)
        public_context["optimization_contract"] = contract
        public_context["public_optimization_contract"] = copy.deepcopy(contract)
        public_context["public_objective_spec"] = public_spec
        public_context["public_objective_spec_text"] = render_public_objective_spec(public_spec)
        public_context["objective_sense"] = contract.get("objective_sense")
        public_context["multi_objective"] = contract.get("objective_mode") == "multi_objective"
    episode["public_context"] = public_context
    return episode


def public_objective_spec_from_contract(contract: dict[str, Any]) -> dict[str, Any]:
    """Return the public, method-neutral part of an optimization contract."""

    keys = [
        "version",
        "benchmark_family",
        "objective_mode",
        "solution_cardinality",
        "objective_sense",
        "objective_names",
        "hard_constraints",
        "objective_terms",
        "scalar_formula",
        "required_diagnostics",
        "diagnostics",
        "solution_output_format",
        "candidate_archive_format",
        "search_space_requirements",
        "update_contract",
        "instruction",
    ]
    return {key: copy.deepcopy(contract[key]) for key in keys if key in contract}


def append_public_objective_spec_to_text(text: str, contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict) or not contract:
        return text
    if PUBLIC_OBJECTIVE_SPEC_MARKER in text or any(marker in text for marker in LEGACY_PUBLIC_OBJECTIVE_SPEC_MARKERS):
        return text
    spec_text = render_public_objective_spec(public_objective_spec_from_contract(contract))
    if not spec_text:
        return text
    return text.rstrip() + "\n\n" + spec_text


def append_public_update_objective_note_to_text(text: str, contract: dict[str, Any] | None) -> str:
    if not isinstance(contract, dict) or not contract:
        return text
    if PUBLIC_UPDATE_OBJECTIVE_NOTE_MARKER in text or any(marker in text for marker in LEGACY_PUBLIC_UPDATE_OBJECTIVE_NOTE_MARKERS):
        return text
    note = render_public_update_objective_note(public_objective_spec_from_contract(contract))
    if not note:
        return text
    return text.rstrip() + "\n\n" + note


def append_public_update_objective_notes_to_episode(episode: dict[str, Any]) -> dict[str, Any]:
    public_context = episode.get("public_context") if isinstance(episode.get("public_context"), dict) else {}
    contract = public_context.get("optimization_contract")
    if not isinstance(contract, dict):
        return episode
    updates = episode.get("update_stream")
    if not isinstance(updates, list):
        return episode
    for update in updates:
        if not isinstance(update, dict):
            continue
        text = str(update.get("public_update") or update.get("natural_language_update") or "")
        patched = append_public_update_objective_note_to_text(text, contract)
        update["public_update"] = patched
        update["natural_language_update"] = patched
    return episode


def render_public_objective_spec(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec:
        return ""
    lines = [PUBLIC_OBJECTIVE_SPEC_MARKER]
    mode = spec.get("objective_mode")
    names = spec.get("objective_names")
    if mode == "multi_objective":
        lines.append(f"- Return a set of trade-off plans. Compare plans using these separate minimization goals, in order: {_join(names)}.")
    elif mode == "exact_single_objective":
        lines.append(f"- Return one best plan for this score: {_join(names)}.")
    else:
        lines.append(f"- Return one plan with the lowest score for: {_join(names)}.")
    hard = spec.get("hard_constraints")
    if isinstance(hard, list) and hard:
        lines.append("- Feasibility rules: " + " ".join(str(item).rstrip(".") + "." for item in hard))
    terms = spec.get("objective_terms")
    if isinstance(terms, list) and terms:
        lines.append("- How to compute the score components:")
        for term in terms:
            if not isinstance(term, dict):
                continue
            name = str(term.get("name") or "term")
            formula = str(term.get("formula") or "").strip()
            weight = term.get("weight")
            weight_source = term.get("weight_source")
            weight_text = ""
            if weight is not None:
                weight_text = f" weight {weight};"
            elif weight_source:
                weight_text = f" use the weight in {weight_source};"
            source = str(term.get("source") or "").strip()
            source_text = f" read values from {source};" if source else ""
            lines.append(f"  * {name}:{weight_text}{source_text} formula: {formula}.")
    scalar_formula = spec.get("scalar_formula")
    if scalar_formula:
        lines.append(f"- Overall scoring rule: {scalar_formula}.")
    required = spec.get("required_diagnostics")
    if isinstance(required, list) and required:
        lines.append(f"- Also report these score components so the plan can be checked: {_join(required)}.")
    diagnostics = spec.get("diagnostics")
    if isinstance(diagnostics, list) and diagnostics:
        lines.append(f"- Track these as reporting-only quantities, not feasibility rules: {_join(diagnostics)}.")
    solution_format = spec.get("solution_output_format") if isinstance(spec.get("solution_output_format"), dict) else {}
    if solution_format:
        lines.append(f"- Required plan output format: {solution_format.get('description') or ''}")
        example = solution_format.get("example")
        if example is not None:
            lines.append(f"  Example shape: {example}.")
        alternatives = solution_format.get("accepted_alternatives")
        if alternatives:
            lines.append(f"  Equivalent accepted forms: {_join(alternatives)}.")
    archive_format = spec.get("candidate_archive_format") if isinstance(spec.get("candidate_archive_format"), dict) else {}
    if archive_format:
        lines.append(f"- For a trade-off set, each candidate must use this plan format: {archive_format.get('description') or ''}")
    search_requirements = spec.get("search_space_requirements")
    if isinstance(search_requirements, list) and search_requirements:
        lines.append("- Search-space requirements:")
        for requirement in search_requirements:
            if not isinstance(requirement, dict):
                continue
            description = requirement.get("description")
            if description:
                lines.append(f"  * {description}")
            metadata = requirement.get("required_segment_metadata")
            if isinstance(metadata, dict):
                for key, value in metadata.items():
                    lines.append(f"    Segment metadata: {key}: {value}")
    update_contract = spec.get("update_contract") if isinstance(spec.get("update_contract"), dict) else {}
    if update_contract:
        if update_contract.get("preserve_terms_unless_explicitly_changed"):
            lines.append("- Later natural-language updates preserve these objective terms unless they explicitly change a listed public term or public weight.")
        if update_contract.get("history_dependent_hard_constraints_allowed") is False:
            lines.append("- Do not introduce hard constraints that depend on the previous solution or the historical trajectory.")
    return "\n".join(lines)


def render_public_update_objective_note(spec: dict[str, Any]) -> str:
    if not isinstance(spec, dict) or not spec:
        return ""
    lines = [PUBLIC_UPDATE_OBJECTIVE_NOTE_MARKER]
    mode = spec.get("objective_mode")
    names = spec.get("objective_names")
    if mode == "multi_objective":
        lines.append(f"- After applying the requested change, compare trade-off plans using the same separate goals, in order: {_join(names)}.")
    else:
        lines.append(f"- After applying the requested change, score the plan using the same score: {_join(names)}.")
    scalar_formula = spec.get("scalar_formula")
    if scalar_formula:
        lines.append(f"- Current scoring rule: {scalar_formula}.")
    terms = spec.get("objective_terms")
    if isinstance(terms, list) and terms:
        term_names = [str(term.get("name")) for term in terms if isinstance(term, dict) and term.get("name")]
        if term_names:
            lines.append(f"- The score components are: {_join(term_names)}.")
    required = spec.get("required_diagnostics")
    if isinstance(required, list) and required:
        lines.append(f"- Keep reporting these score components for checking: {_join(required)}.")
    solution_format = spec.get("solution_output_format") if isinstance(spec.get("solution_output_format"), dict) else {}
    if solution_format:
        lines.append(f"- Keep using this plan output format: {solution_format.get('description') or ''}")
    lines.append("- If this update changes a weight, target, due time, priority, cost, emission, energy, or policy value, use the updated value in the same scoring rule.")
    lines.append("- If this update explicitly changes the scoring rule, use the new rule stated above and keep all unchanged terms as before.")
    lines.append("- Do not introduce hard constraints that depend on the previous solution or historical trajectory; history may only resolve references to public entities or public fields.")
    return "\n".join(lines)


def _join(value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    if value is None:
        return ""
    return str(value)


def _base_contract(**fields: Any) -> dict[str, Any]:
    contract = {
        "version": "public_quantitative_objective_contract_v1",
        "source": "public_profile_contract",
        "preserve_across_updates": True,
        "forbidden_inputs": [
            "hidden_delta",
            "hidden_reference",
            "reference_solution",
            "reference_archive",
            "hidden_evaluator_implementation",
        ],
    }
    contract.update(fields)
    return contract


def _cobench_contract(family: str, episode: dict[str, Any]) -> dict[str, Any]:
    if family == "facility_location":
        return _base_contract(
            benchmark_family="cobench_exact_small:facility_location",
            objective_mode="exact_single_objective",
            solution_cardinality="single_solution",
            required_solver_mode="linear_mip_when_representable",
            objective_sense="minimize",
            objective_names=["public_facility_assignment_cost"],
            hard_constraints=[
                "Every public customer row is assigned to exactly one open facility.",
                "Only facilities not listed as forbidden may be opened; all mandatory facilities must be open.",
                "For each facility, assigned public demand must not exceed its public capacity.",
            ],
            objective_terms=[
                {
                    "name": "opening_cost",
                    "kind": "objective",
                    "weight": 1.0,
                    "formula": "sum(open_facility[f] * facilities.open_cost[f])",
                    "source": "public facilities table",
                },
                {
                    "name": "service_cost",
                    "kind": "objective",
                    "weight": 1.0,
                    "formula": "sum(assign[c,f] * customers.demand[c] * customers.serve_cost_<f>[c])",
                    "source": "public customers table demand and service-cost columns",
                },
            ],
            scalar_formula="opening_cost + service_cost, unless constraints.objective_mode explicitly selects a public alternative.",
            solution_output_format={
                "root_key": "open_facilities_and_assignments",
                "description": "Return a JSON object with open_facilities as a list of facility ids and assignments as a mapping from each customer id to one open facility id.",
                "example": {"open_facilities": ["F1"], "assignments": {"C01": "F1"}},
                "required_keys": ["open_facilities", "assignments"],
            },
            update_contract=_shared_exact_update_contract(["facilities.open_cost", "customers.serve_cost_*", "constraints.objective_mode"]),
            instruction="Build all variables and coefficients by looping over public facilities/customers/constraints rows.",
        )
    if family == "set_cover":
        return _base_contract(
            benchmark_family="cobench_exact_small:set_cover",
            objective_mode="exact_single_objective",
            solution_cardinality="single_solution",
            required_solver_mode="linear_mip_when_representable",
            objective_sense="minimize",
            objective_names=["selected_set_cost"],
            hard_constraints=[
                "Every active public element must be covered by at least one selected active set.",
                "All public mandatory sets must be selected and all public forbidden sets must be excluded.",
            ],
            objective_terms=[
                {
                    "name": "selected_set_cost",
                    "kind": "objective",
                    "weight": 1.0,
                    "formula": "sum(select[s] * sets.cost[s])",
                    "source": "public sets table",
                }
            ],
            scalar_formula="selected_set_cost",
            solution_output_format={
                "root_key": "selected_sets",
                "description": "Return a JSON object with selected_sets as a list of selected public set ids.",
                "example": {"selected_sets": ["S01", "S03"]},
                "required_keys": ["selected_sets"],
            },
            update_contract=_shared_exact_update_contract(["sets.cost", "sets.active", "elements.active", "constraints.mandatory", "constraints.forbidden"]),
            instruction="Represent coverage by looping over sets.covers and active elements; do not enumerate source-specific set ids.",
        )
    return _base_contract(
        benchmark_family="cobench_exact_small:knapsack",
        objective_mode="exact_single_objective",
        solution_cardinality="single_solution",
        required_solver_mode="linear_mip_when_representable",
        objective_sense="optimize_scalar",
        objective_names=["portfolio_value_or_weight"],
        hard_constraints=[
            "Total public weight of selected items must not exceed constraints.capacity.",
            "All public mandatory items must be selected and all public forbidden items must be excluded.",
            "If constraints.objective_mode is minimize_weight_with_value_floor, total value must meet constraints.value_floor.",
        ],
        objective_terms=[
            {
                "name": "total_value",
                "kind": "objective",
                "weight": 1.0,
                "formula": "sum(select[i] * items.value[i])",
                "source": "public items table",
            },
            {
                "name": "total_weight",
                "kind": "objective",
                "weight": 1.0,
                "formula": "sum(select[i] * items.weight[i])",
                "source": "public items table",
            },
        ],
        scalar_formula="If constraints.objective_mode is maximize_value, maximize total_value. If it is minimize_weight_with_value_floor, minimize total_weight subject to value_floor.",
        solution_output_format={
            "root_key": "selected_items",
            "description": "Return a JSON object with selected_items as a list of selected public item ids.",
            "example": {"selected_items": ["I01", "I04"]},
            "required_keys": ["selected_items"],
        },
        update_contract=_shared_exact_update_contract(["items.value", "items.weight", "constraints.objective_mode", "constraints.value_floor"]),
        instruction="Read objective_mode from the singleton public constraints table; do not hard-code one knapsack variant.",
    )


def _fjsp_contract() -> dict[str, Any]:
    return _base_contract(
        benchmark_family="fjsp_exact_small:flexible_job_shop",
        objective_mode="exact_single_objective",
        solution_cardinality="single_solution",
        required_solver_mode="linear_mip_when_representable",
        objective_sense="minimize",
        objective_names=["weighted_tardiness"],
        hard_constraints=[
            "Each public operation row is assigned to exactly one eligible machine from operations.eligible_machines.",
            "Within each public job, operations respect increasing sequence_index precedence.",
            "A machine cannot process two assigned operations at overlapping times.",
            "Only public machines with available=true may be used.",
        ],
        objective_terms=[
            {
                "name": "weighted_tardiness",
                "kind": "objective",
                "weight": 1.0,
                "formula": "sum(operations.priority[op] * max(0, finish_time[op] - operations.due_time[op]))",
                "source": "public operations table",
            },
            {
                "name": "machine_processing_cost",
                "kind": "objective",
                "weight": 1.0,
                "formula": "sum(assign[op,m] * operations.processing_time[op] * machines.cost_rate[m])",
                "source": "public operations and machines tables",
            },
        ],
        scalar_formula="Use settings.objective_mode: minimize_tardiness uses weighted_tardiness; minimize_cost uses machine_processing_cost; combined modes sum the listed public terms.",
        diagnostics=["plan_change_disruption"],
        solution_output_format={
            "root_key": "assignments",
            "description": "Return assignments as a mapping from each operation_id to an object with machine, start, and end fields.",
            "example": {"assignments": {"J1O1": {"machine": "M1", "start": 0, "end": 5}}},
            "required_keys": ["assignments"],
        },
        update_contract=_shared_exact_update_contract(["operations.due_time", "operations.priority", "machines.cost_rate", "settings.objective_mode"]),
        instruction="A compact MILP with start times, assignment variables, precedence, non-overlap, and tardiness variables is preferred for small tables.",
    )


def _inrc_contract() -> dict[str, Any]:
    return _base_contract(
        benchmark_family="inrc_realistic_dynamic:coverage_roster",
        objective_mode="single_objective",
        solution_cardinality="single_solution",
        required_solver_mode="scalar_ga",
        objective_sense="minimize",
        objective_names=["public_roster_penalty"],
        hard_constraints=[
            "Coverage shortage should be zero for every public coverage(day, shift) requirement whenever enough eligible nurses exist.",
            "A nurse cannot work more than one shift on the same public day.",
            "A public absence row forbids assigning that nurse on that day.",
            "Per-nurse max_shifts and public nurse_limits rows are hard or high-priority feasibility terms.",
        ],
        objective_terms=[
            {
                "name": "coverage_shortage",
                "kind": "hard_penalty",
                "weight": 1000.0,
                "formula": "sum(max(0, coverage.required[day,shift] - assigned_count[day,shift]))",
                "source": "public coverage table",
                "required_public_tables": ["coverage"],
                "required_diagnostic": True,
            },
            {
                "name": "absence_violations",
                "kind": "hard_penalty",
                "weight": 500.0,
                "formula": "count(assignments that match a public absences(nurse, day) row)",
                "source": "public absences table",
                "required_public_tables": ["absences"],
                "required_diagnostic": True,
            },
            {
                "name": "overload_penalty",
                "kind": "soft_penalty",
                "weight_source": "policy.overload_weight",
                "formula": "sum(max(0, shifts_assigned[nurse] - nurses.max_shifts[nurse])) plus matching nurse_limits excess",
                "source": "public nurses, nurse_limits, and policy tables",
                "required_public_tables": ["nurses", "nurse_limits", "policy"],
                "required_diagnostic": True,
            },
            {
                "name": "over_coverage",
                "kind": "soft_penalty",
                "weight_source": "policy.over_coverage_weight",
                "formula": "sum(max(0, assigned_count[day,shift] - coverage.required[day,shift]))",
                "source": "public coverage and policy tables",
                "required_diagnostic": True,
            },
            {
                "name": "fairness_penalty",
                "kind": "soft_penalty",
                "weight_source": "policy.fairness_weight",
                "formula": "load-variance or absolute deviation of per-nurse assignment counts",
                "source": "public nurses and policy tables",
                "required_diagnostic": True,
            },
            {
                "name": "preference_penalty",
                "kind": "soft_penalty",
                "weight_source": "policy.preference_weight",
                "formula": (
                    "count assignments that violate public preferences rows, especially preference=off/avoid; "
                    "if a preference row has nurse and day but no shift column, the preference applies to every shift "
                    "worked by that nurse on that day"
                ),
                "source": "public preferences and policy tables",
                "required_public_tables": ["preferences", "policy"],
                "optional_field_semantics": [
                    {
                        "table": "preferences",
                        "field": "shift",
                        "when_missing": "the preference applies to the whole public day for that nurse",
                        "must_not_gate_term": True,
                    }
                ],
                "required_diagnostic": True,
            },
            {
                "name": "sequence_penalty",
                "kind": "soft_penalty",
                "weight_source": "policy.sequence_weight",
                "formula": "count disallowed public sequence patterns such as avoid_evening_after_night",
                "source": "public policy table",
                "required_public_tables": ["policy"],
                "required_diagnostic": True,
            },
        ],
        required_diagnostics=[
            "coverage_shortage",
            "absence_violations",
            "overload_penalty",
            "over_coverage",
            "fairness_penalty",
            "preference_penalty",
            "sequence_penalty",
        ],
        solution_output_format={
            "root_key": "roster",
            "description": "Return roster as a mapping from 'nurse_id|day_id' to shift_id, for example {'N004|D2': 'night'}. This format naturally enforces at most one shift per nurse per day.",
            "example": {"roster": {"N004|D2": "night"}},
            "required_keys": ["roster"],
            "accepted_alternatives": [
                "assignments as a list of objects with nurse, day, and shift fields",
                "assignments as a list of triples [nurse, day, shift]",
            ],
        },
        search_space_requirements=[
            {
                "name": "per_coverage_slot_staff_assignment",
                "kind": "per_demand_assignment",
                "description": "The decision space must be able to choose a nurse for each required day/shift coverage position. A single global nurse priority order is not expressive enough when workload fairness and preferences are optimized.",
                "allowed_segment_kinds": ["assignment", "optional_assignment", "choice_vector"],
                "min_demands_from_table": {"table": "coverage", "column": "required"},
                "required_segment_metadata": {
                    "exclusive_resource_per_group": (
                        "For assignment encodings, map each generated coverage-slot demand to its public day "
                        "and set capacity=1, because one nurse can work at most one shift on the same public day."
                    ),
                    "resource_total_capacity": (
                        "For assignment encodings, map each nurse/resource id to its public total max_shifts or "
                        "equivalent planning-horizon capacity so the generic repair operator can preserve total workload limits."
                    ),
                },
            }
        ],
        diagnostic_policy="required_for_generated_fitness",
        scalar_formula=(
            "1000*coverage_shortage + 500*absence_violations + "
            "policy.overload_weight*overload_penalty + policy.over_coverage_weight*over_coverage + "
            "policy.fairness_weight*fairness_penalty + policy.preference_weight*preference_penalty + "
            "policy.sequence_weight*sequence_penalty"
        ),
        diagnostics=["plan_change_disruption"],
        update_contract={
            "preserve_terms_unless_explicitly_changed": True,
            "data_updates_may_change": [
                "nurses.max_shifts",
                "coverage.required",
                "absences",
                "preferences",
                "nurse_limits",
                "policy.fairness_weight",
                "policy.preference_weight",
                "policy.sequence_weight",
                "policy.overload_weight",
                "policy.over_coverage_weight",
                "policy.avoid_evening_after_night",
            ],
            "objective_updates_may_change": ["public policy weights only when the update explicitly names the policy change"],
            "history_dependent_hard_constraints_allowed": False,
        },
        instruction="Expand coverage demand slots or use an equivalent generic roster encoding; compute every listed term by looping over public tables.",
    )


def _green_vrp_contract(episode: dict[str, Any]) -> dict[str, Any]:
    objective_names = _objective_names(episode, ["distance", "lateness", "emission"])
    return _base_contract(
        benchmark_family="green_vrp_mo:dynamic_service_routing",
        objective_mode="multi_objective",
        solution_cardinality="pareto_archive",
        required_solver_mode="moea",
        objective_sense="minimize_all",
        objective_names=objective_names,
        hard_constraints=[
            "Every active public order row is served exactly once.",
            "Only available public vehicles may be used.",
            "For each vehicle route, total public demand must not exceed vehicles.capacity.",
            "Route timing must use depot/order coordinates, ready/due/service fields, and vehicle shift_end where public.",
        ],
        objective_terms=[
            {
                "name": "distance",
                "kind": "pareto_objective",
                "formula": "sum Euclidean route leg distances from depot through assigned active orders and back as applicable",
                "source": "public depot and orders coordinates",
                "required_diagnostic": True,
            },
            {
                "name": "lateness",
                "kind": "pareto_objective",
                "formula": "sum(max(0, service_start_or_arrival[order] - orders.due[order])) over active orders",
                "source": "public orders table",
                "required_diagnostic": True,
            },
            {
                "name": "emission",
                "kind": "pareto_objective",
                "formula": "sum(route_distance[vehicle] * vehicles.emission_rate[vehicle] * policy.carbon_multiplier)",
                "source": "public vehicles and policy tables",
                "required_diagnostic": True,
            },
        ],
        required_diagnostics=["distance", "lateness", "emission", "priority_penalty"],
        diagnostics=["priority_penalty", "route_disruption"],
        solution_output_format={
            "root_key": "routes",
            "description": "Return routes as a list of route objects; each route has vehicle as a public vehicle id and orders as the ordered list of public order ids served by that vehicle.",
            "example": {"routes": [{"vehicle": "V1", "orders": ["O01", "O03"]}]},
            "required_keys": ["routes"],
        },
        candidate_archive_format={
            "description": "Each archive candidate should contain a solution with routes plus an objectives vector or object for distance, lateness, and emission.",
        },
        scalar_formula="Pareto objectives are not scalarized; base_scalar may be their sum plus penalties for ranking only.",
        update_contract={
            "preserve_terms_unless_explicitly_changed": True,
            "data_updates_may_change": [
                "depot.x",
                "depot.y",
                "orders.x",
                "orders.y",
                "orders.demand",
                "orders.ready",
                "orders.due",
                "orders.service",
                "orders.priority",
                "orders.active",
                "vehicles.capacity",
                "vehicles.available",
                "vehicles.emission_rate",
                "vehicles.shift_end",
                "policy.carbon_multiplier",
            ],
            "history_dependent_hard_constraints_allowed": False,
        },
        instruction="Use assignment/permutation route segments or an equivalent generic encoding; never collapse the three Pareto objectives.",
    )


def _cloud_contract(episode: dict[str, Any]) -> dict[str, Any]:
    objective_names = _objective_names(episode, ["energy", "load_imbalance"])
    return _base_contract(
        benchmark_family="cloud_scheduling_mo:energy_aware_assignment",
        objective_mode="multi_objective",
        solution_cardinality="pareto_archive",
        required_solver_mode="moea",
        objective_sense="minimize_all",
        objective_names=objective_names,
        hard_constraints=[
            "Every active public job row is assigned to exactly one available public machine.",
            "For each machine, assigned public cpu and mem must not exceed machine cpu and mem capacity.",
            "A gpu_required job may only be assigned to a public machine with gpu=true.",
        ],
        objective_terms=[
            {
                "name": "energy",
                "kind": "pareto_objective",
                "formula": "sum(energy_idle for used machines) + sum(assigned job cpu * machine.energy_per_cpu) scaled by global_params when present",
                "source": "public machines, jobs, and global_params tables",
                "required_diagnostic": True,
            },
            {
                "name": "load_imbalance",
                "kind": "pareto_objective",
                "formula": "variance or sum absolute deviation of machine CPU utilization after assignment",
                "source": "public machines and jobs tables",
                "required_diagnostic": True,
            },
        ],
        required_diagnostics=["energy", "load_imbalance", "sla_violations", "latency"],
        diagnostics=["sla_violations", "latency", "migration_disruption"],
        solution_output_format={
            "root_key": "assignments",
            "description": "Return assignments as a mapping from each active public job id to one available public machine id.",
            "example": {"assignments": {"J001": "M02"}},
            "required_keys": ["assignments"],
        },
        candidate_archive_format={
            "description": "Each archive candidate should contain a solution with job-to-machine assignments plus objectives for energy and load_imbalance.",
        },
        scalar_formula="Pareto objectives are not scalarized; base_scalar may be their sum plus penalties for ranking only.",
        update_contract={
            "preserve_terms_unless_explicitly_changed": True,
            "data_updates_may_change": [
                "jobs.cpu",
                "jobs.mem",
                "jobs.gpu_required",
                "jobs.deadline",
                "jobs.latency_sensitivity",
                "jobs.priority",
                "jobs.active",
                "machines.cpu",
                "machines.mem",
                "machines.gpu",
                "machines.available",
                "machines.energy_idle",
                "machines.energy_per_cpu",
                "global_params.energy_price",
                "global_params.carbon_intensity",
            ],
            "history_dependent_hard_constraints_allowed": False,
        },
        instruction="Use public job/machine rows to compute both Pareto dimensions for each genome; diagnostics must not become hidden hard constraints.",
    )


def _generic_contract(episode: dict[str, Any]) -> dict[str, Any]:
    evaluation = episode.get("evaluation") if isinstance(episode.get("evaluation"), dict) else {}
    objectives = _objective_names(episode, [])
    if len(objectives) > 1:
        return _base_contract(
            benchmark_family=_profile_id(episode, None) or "generic_multi_objective",
            objective_mode="multi_objective",
            solution_cardinality="pareto_archive",
            required_solver_mode="moea",
            objective_sense="minimize_all",
            objective_names=objectives,
            hard_constraints=["Use only public hard constraints stated in the task and public tables."],
            objective_terms=[{"name": name, "kind": "pareto_objective", "formula": f"compute public {name} from the candidate solution"} for name in objectives],
            scalar_formula="Do not scalarize public Pareto objectives.",
            update_contract={"preserve_terms_unless_explicitly_changed": True, "history_dependent_hard_constraints_allowed": False},
        )
    reference_policy = str(evaluation.get("reference_policy") or "").lower()
    exact = "exact" in reference_policy
    return _base_contract(
        benchmark_family=_profile_id(episode, None) or "generic_single_objective",
        objective_mode="exact_single_objective" if exact else "single_objective",
        solution_cardinality="single_solution",
        required_solver_mode="linear_mip_when_representable" if exact else "scalar_ga_or_linear_mip",
        objective_sense="optimize_scalar",
        objective_names=objectives or ["public_scalar_objective"],
        hard_constraints=["Use only public hard constraints stated in the task and public tables."],
        objective_terms=[{"name": objectives[0] if objectives else "public_scalar_objective", "kind": "objective", "formula": "compute the public scalar objective from the candidate solution"}],
        scalar_formula="Use the public scalar objective exactly as stated.",
        update_contract={"preserve_terms_unless_explicitly_changed": True, "history_dependent_hard_constraints_allowed": False},
    )


def _shared_exact_update_contract(fields: list[str]) -> dict[str, Any]:
    return {
        "preserve_terms_unless_explicitly_changed": True,
        "data_updates_may_change": fields,
        "objective_updates_may_change": ["public objective_mode or public weights only when explicitly changed"],
        "history_dependent_hard_constraints_allowed": False,
    }


def _profile_id(episode: dict[str, Any], benchmark_name: str | None) -> str:
    for value in [
        benchmark_name,
        episode.get("hidden_evaluator_profile"),
        episode.get("benchmark"),
        episode.get("base_benchmark"),
        episode.get("domain"),
    ]:
        text = str(value or "").strip().lower()
        if text and text != "nldo":
            return text
    public_context = episode.get("public_context") if isinstance(episode.get("public_context"), dict) else {}
    source_id = str(public_context.get("nldo_source_id") or "").strip().upper()
    return {
        "S01": "cobench_exact_small",
        "S02": "fjsp_exact_small",
        "S03": "inrc_realistic_dynamic",
        "S04": "green_vrp_mo",
        "S05": "cloud_scheduling_mo",
    }.get(source_id, "")


def _family_id(episode: dict[str, Any], public_context: dict[str, Any]) -> str:
    state = episode.get("hidden_initial_state") if isinstance(episode.get("hidden_initial_state"), dict) else {}
    family = str(state.get("family") or episode.get("family") or "").strip().lower()
    if family:
        return family
    schema = public_context.get("csv_schema") if isinstance(public_context.get("csv_schema"), dict) else {}
    tables = set(str(name) for name in schema)
    if {"facilities", "customers"} <= tables:
        return "facility_location"
    if {"sets", "elements"} <= tables:
        return "set_cover"
    if "items" in tables:
        return "knapsack"
    return ""


def _objective_names(episode: dict[str, Any], default: list[str]) -> list[str]:
    evaluation = episode.get("evaluation") if isinstance(episode.get("evaluation"), dict) else {}
    names = [str(item) for item in evaluation.get("objectives", []) if str(item)]
    return names or list(default)
