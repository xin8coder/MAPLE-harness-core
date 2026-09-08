from __future__ import annotations

import json
from textwrap import dedent
from typing import Any


def runnable_mvp_project_code() -> str:
    """A complete, runnable MVP shown to the LLM as the editing base.

    The code deliberately combines several encoding primitives. The model should
    edit this project, not invent a new framework.
    """

    return dedent(
        '''
        ### setup.py
        ```python
        def build_problem(public_context):
            # LiveOpt Workbench data slot: parse public tables, build data, declare bounds/segments.
            tables = public_context.get("tables") or public_context.get("csv_tables")
            if tables is None and isinstance(public_context.get("public_data"), dict):
                public_data = public_context["public_data"]
                tables = public_data.get("tables") or public_data.get("csv_tables") or public_data
            if tables is None:
                tables = public_context

            tasks = []
            for row in tables.get("tasks", []):
                tasks.append({
                    "id": row.get("id"),
                    "load": float(row.get("load", row.get("demand", 1))),
                })

            workers = []
            for row in tables.get("workers", []):
                workers.append({
                    "id": row.get("id"),
                    "capacity": float(row.get("capacity", 0)),
                    "cost_per_load": float(row.get("cost_per_load", row.get("cost", 1))),
                })

            task_ids = [row["id"] for row in tasks if row.get("id") is not None]
            worker_ids = [row["id"] for row in workers if row.get("id") is not None]
            data = {
                "tasks": tasks,
                "workers": workers,
                "task_by_id": {row["id"]: row for row in tasks},
                "worker_by_id": {row["id"]: row for row in workers},
            }

            return {
                "data": data,
                "segments": [
                    # Main discrete mapping: each demand/task chooses one resource/worker.
                    {"name": "assign", "kind": "assignment", "demands": task_ids, "resources": worker_ids},
                    # Ordering primitive: useful when a route, schedule, priority list, or greedy split is needed.
                    {"name": "priority", "kind": "permutation", "values": task_ids},
                    # Binary primitive: useful for open/closed, selected/unselected, activated/deactivated choices.
                    {"name": "open_worker", "kind": "binary_vector", "length": len(worker_ids)},
                    # Continuous primitive: useful for policy weights, thresholds, speed/quantity decisions, or penalties.
                    {"name": "policy", "kind": "real_vector", "length": 2, "lower": 0.0, "upper": 1.0},
                ],
                "solver_mode": "moea",
                "sense": "min",
                "objective_names": ["cost", "capacity_balance"],
                "constraint_names": ["all_tasks_assigned", "worker_capacity"],
            }
        ```
        ### fitness.py
        ```python
        def evaluate(genome, data):
            # LiveOpt Workbench fitness slot: evaluate one chromosome x using data.
            assignments = dict(genome.get("assign", {}))
            priority = list(genome.get("priority", [row["id"] for row in data["tasks"]]))
            open_flags = list(genome.get("open_worker", []))
            policy = list(genome.get("policy", [0.5, 0.5]))

            worker_ids = [row["id"] for row in data["workers"]]
            open_workers = set()
            for idx, worker_id in enumerate(worker_ids):
                if not open_flags or idx >= len(open_flags) or int(open_flags[idx]) == 1:
                    open_workers.add(worker_id)
            if not open_workers:
                open_workers = set(worker_ids)

            used = {worker_id: 0.0 for worker_id in worker_ids}
            missing = 0
            assigned_to_closed = 0
            cost = 0.0
            ordered_task_ids = [task_id for task_id in priority if task_id in data["task_by_id"]]
            for task in data["tasks"]:
                if task["id"] not in ordered_task_ids:
                    ordered_task_ids.append(task["id"])

            decoded = {}
            for task_id in ordered_task_ids:
                task = data["task_by_id"][task_id]
                worker_id = assignments.get(task_id)
                if worker_id not in data["worker_by_id"]:
                    missing += 1
                    continue
                if worker_id not in open_workers:
                    assigned_to_closed += 1
                worker = data["worker_by_id"][worker_id]
                load = float(task.get("load", 0.0))
                used[worker_id] += load
                cost += load * float(worker.get("cost_per_load", 1.0))
                decoded[task_id] = worker_id

            capacity_excess = 0.0
            for worker in data["workers"]:
                worker_id = worker["id"]
                capacity_excess += max(0.0, used[worker_id] - float(worker.get("capacity", 0.0)))
            loads = list(used.values())
            mean_load = sum(loads) / max(1, len(loads))
            balance = sum((load - mean_load) ** 2 for load in loads)
            base_scalar = cost + float(policy[0] if policy else 0.0) * balance

            violations = {}
            if missing:
                violations["missing_tasks"] = missing
            if assigned_to_closed:
                violations["assigned_to_closed_worker"] = assigned_to_closed
            if capacity_excess:
                violations["worker_capacity_excess"] = capacity_excess

            solution = {
                "assignments": decoded,
                "used_capacity": used,
                "open_workers": sorted(open_workers),
            }
            return penalty_result(base_scalar, violations, objectives=[cost, balance], solution=solution)
        ```
        '''
    ).strip()


def build_scaffold_prompt(
    problem: str,
    public_context: dict[str, Any] | None = None,
    skills: str = "",
    *,
    previous_error: str = "",
    previous_slots: dict[str, str] | None = None,
) -> str:
    table_summary = summarize_tables_for_prompt(_extract_prompt_tables(public_context or {}))
    optimization_contract = _public_scoring_text(public_context or {}) or _format_optimization_contract(_public_prompt_contract(public_context or {}))
    repair_feedback = ""
    if previous_error:
        repair_feedback = dedent(
            f"""

            Previous Workbench attempt failed during compile or smoke execution.
            Repair the code while preserving the same public-data contract.
            Error feedback:
            {previous_error.strip()}

            Previous setup.py:
            ```python
            {(previous_slots or {}).get("setup.py", "").strip()}
            ```

            Previous fitness.py:
            ```python
            {(previous_slots or {}).get("fitness.py", "").strip()}
            ```
            """
        ).strip()
    return dedent(
        f"""
        You are editing a fixed LiveOpt Workbench. The Workbench is a runnable
        optimization workspace with two model-owned slots and framework-owned
        optimization machinery.

        The framework already owns:
        - main loop, population initialization, GA/NSGA-II selection;
        - LP/MILP solving for small exact linearly representable tasks;
        - crossover/mutation for each segment kind;
        - nondominated sorting, crowding distance, archive tracking;
        - penalty ranking through penalty_result(base, violations, objectives, solution).

        Below is a complete runnable MVP project. Start from this code and make
        the smallest necessary edits for the user's problem. Preserve the two
        slot names and function signatures.

        Runnable MVP editing base:
        {runnable_mvp_project_code()}

        You write exactly two revised Python slots in one response:
        1. setup.py: read/normalize public data and declare the search space.
        2. fitness.py: evaluate one genome from the declared segments and data.

        Do not generate a separate intermediate model or GA/NSGA code. Do not
        create a large JSON contract. Do not hardcode concrete entity IDs, resource
        names, location names, staff names, task names, or source-specific IDs.
        All submitted solution identifiers must be scalar public IDs copied
        from public rows. Never place an entire row dict/list/object in fields
        such as vehicle, resource, machine, worker, order, task, job, item, or
        any *_id field; keep row details in data and submit only the public id.
        Keep the response compact: no prose, no docstrings, no long comments,
        and no unused helper code. Always complete both code blocks.

        setup.py contract:
        def build_problem(public_context):
            ...
            return {{
                "data": data,
                "segments": [
                    # each segment is a plain dict:
                    # real_vector: {{"name": "x", "kind": "real_vector", "length": n, "lower": 0, "upper": 1}}
                    # int_vector: {{"name": "x", "kind": "int_vector", "length": n, "lower": 0, "upper": k}}
                    # binary_vector: {{"name": "x", "kind": "binary_vector", "length": n}}
                    # permutation: {{"name": "order", "kind": "permutation", "values": ids}}
                    # choice_vector: {{"name": "choice", "kind": "choice_vector", "length": n, "options": ids}}
                    # assignment: {{"name": "assign", "kind": "assignment", "demands": demand_ids, "resources": resource_ids}}
                    # optional_assignment: same as assignment plus "allow_none": True
                    # assignment metadata for reusable group-capacity repair:
                    # {{"exclusive_resource_per_group": {{"demand_to_group": {{"d1": "g1"}}, "capacity": 1}}}}
                    # Use this when the public rules say one resource/staff/vehicle/machine can serve at most
                    # k demands inside the same visible group such as day, time slot, room, shift block, or route period.
                    # assignment metadata for reusable total-capacity repair:
                    # {{"resource_total_capacity": {{"resource_capacity": {{"r1": 5, "r2": 4}}}}}}
                    # Use this when public rows give a total limit per resource over the planning horizon,
                    # such as staff max_shifts, worker max_hours, vehicle max_jobs, or machine total capacity.
                    # assignment metadata for reusable open-resource gate repair:
                    # {{"resource_open_gate": {{"segment": "open_resource", "resources": resource_ids, "open_value": 1}}}}
                    # Use this whenever an assignment segment chooses resources and another binary/int/choice
                    # segment controls whether those resources are open, active, rented, selected, or enabled.
                    # The resources list must be in the same order as the gate segment positions.
                ],
                # Choose exactly one runtime mode:
                # linear_mip: small exact LP/MILP tasks with a complete linear_program_spec.
                # scalar_ga: larger single-objective combinatorial problems, e.g. scheduling or rostering.
                # moea: multi-objective problems with a Pareto archive.
                "solver_mode": "linear_mip" | "scalar_ga" | "moea",
                # Required when solver_mode == "linear_mip". Build it with loops from public data;
                # do not write symbolic placeholders.
                "linear_program_spec": {{
                    "sense": "minimize" | "maximize",
                    "variables": [{{"name": "...", "type": "binary|integer|continuous", "lb": 0, "ub": 1}}],
                    "objective": {{"coefficients": {{"var_name": 1.0}}}},
                    "constraints": [
                        {{"name": "...", "coefficients": {{"var_name": 1.0}}, "sense": "<=|>=|=", "rhs": 0.0}}
                    ],
                    "solution_extraction": {{"type": "selected_variables|binary_selection|open_resource_assignment|generic_assignment|solver_values"}}
                }},
                "sense": "min",
                "objective_names": ["..."],
                "constraint_names": ["..."],
            }}

        fitness.py contract:
        def evaluate(genome, data):
            # genome is the framework chromosome dictionary.
            # Compute decoded solution locally, then return penalty_result(...).
            return penalty_result(base_scalar, violations, objectives=[...], solution=solution)

        Public objective/scoring specification:
        {optimization_contract or "(none supplied; infer conservatively from the problem statement)"}

        Contract-following rule:
        - Treat the public optimization contract as authoritative public input.
        - If objective_mode is "multi_objective", setup.py must set
          solver_mode="moea", objective_names must exactly match the contract
          objective_names, and fitness.py must return objectives=[...] in that
          same order. Do not collapse these objectives into one scalar; use
          base_scalar only for penalty ranking or diagnostics. Never put a
          literal constant such as 0, 0.0, or 1.0 into the Pareto objective
          vector; every objective dimension must be computed from public data
          and the current genome/solution.
        - If required_solver_mode is "linear_mip" or
          "linear_mip_when_representable", setup.py must set
          solver_mode="linear_mip" and include a complete numeric public
          linear_program_spec. Do not fall back to scalar_ga for such tasks.
        - If objective_mode is "exact_single_objective" but no linear solver
          requirement is stated, prefer solver_mode="linear_mip" with a
          complete numeric public LP/MILP spec when representable; otherwise
          produce one scalar solution.
        - If objective_mode is "single_objective", return one scalar solution
          with objectives=[base_scalar] unless a complete LP/MILP spec is used.
        - If the contract lists objective_terms, fitness.py must compute each
          term from public data and the current genome/solution using loops over
          public rows. Do not replace listed terms with a coarse proxy or a
          different private objective. Assemble base_scalar from the listed
          scalar_formula and public table weights.
        - If the contract lists required_diagnostics or terms marked
          required_diagnostic, return those component values in
          penalty_result(..., diagnostics={{...}}). Use the exact public names
          from the contract so hidden/reference scoring can compare the same
          quantities.
        - If weights are stored in public singleton tables such as policy,
          settings, constraints, or global_params, setup.py must copy them into
          data and fitness.py must read them from data; never hard-code a
          stage-specific weight from the prompt.
        - If the scoring rules specify a required plan output format, the
          solution returned by penalty_result must follow that public format.
          Do not invent a different top-level structure when the user has
          specified selected_items, selected_sets, routes, roster, or
          assignments.
        - If the scoring rules specify search-space requirements, choose
          segments that can actually express those decisions. For example, a
          per-slot assignment requirement needs an assignment/choice segment
          for the demand slots; a single global priority list is not enough.
        - If the public rules include a group-capacity restriction such as one
          staff member per day, one room per time slot, or one vehicle per
          period, put the reusable assignment metadata
          exclusive_resource_per_group={{"demand_to_group": ..., "capacity": k}}
          on the assignment segment so the framework can initialize and repair
          chromosomes without problem-specific code.

        Variable placement rule:
        - At the top of build_problem, always normalize input tables with:
          tables = public_context.get("tables") or public_context.get("csv_tables")
          and then unwrap public_context["public_data"] if needed. Never assume
          domain tables are top-level keys.
        - Treat every public table as a list of row dictionaries:
          tables[table_name] == list[dict]. Even singleton configuration tables
          such as policy, settings, depot, or global_params must be read as
          rows = tables.get(name, []); row = rows[0] if rows else {{}}.
          Never use tables[name]["field"] for a table, and never convert a
          table into a dict keyed by entity id unless you keep that lookup in
          data under a separate name.
        - Public table columns are authoritative. Do not invent renamed columns
          such as *_id, *_code, max_*_limit, or canonical aliases unless
          setup.py explicitly maps them from actual visible columns. If a table
          row contains "nurse", "worker", "machine", "day", "shift", "limit",
          "preference", or any other public column, read that exact key or map
          it once in setup.py; do not later read a different guessed key in
          fitness.py.
        - Do not make a listed objective term depend on a public column that is
          absent from the visible table schema. If a row lacks an optional
          qualifier such as shift, room, or time_slot, apply the row at the
          coarser visible level described by the scoring rules instead of
          silently ignoring it.
        - When setup.py normalizes rows, keep a clear data contract: either
          preserve public column names unchanged, or create normalized dicts
          with explicit assignments from public fields. fitness.py must use
          only fields that setup.py actually writes into data.
        - Keep IDs as public row values and loop over rows; do not assume
          positions such as tables[name][0] exist unless you first guard empty
          tables.
        - Put reusable parsed tables, lookup maps, capacities, distances, bounds,
          and ID lists in setup.py under data so fitness.py can evaluate each
          candidate without reparsing the public context.
        - Put only per-candidate variables such as selected worker, route load,
          schedule time, violation amounts, and decoded solution in fitness.py.

        Solver-mode rule:
        - For one-scalar-objective tasks with small public tables and linear or
          linearly representable constraints, prefer solver_mode="linear_mip".
          Do not choose scalar_ga merely because the model has binary choices,
          assignment choices, precedence, or ordering decisions.
        - For small exact/solver tasks such as subset selection, covering,
          open-resource assignment, compact assignment, or any scalar linearly
          representable public-table task, set solver_mode="linear_mip" and
          emit a complete numeric linear_program_spec. Do not use enumeration for these tasks.
          Build variables, objective coefficients, constraints, and
          solution_extraction by looping over public tables in setup.py.
          The solution_extraction must produce the actual submitted plan, such
          as selected_items, open_facilities plus assignments, generic
          assignments, or a precedence_schedule. Do not use raw solver_values
          as the only solution for a scheduling or assignment problem.
          For generic assignments, one compact option is:
          {{"type": "generic_assignment",
            "assignment_from_variables": {{"x_<demand>_<resource>": ["<demand_id>", "<resource_id>"]}}}}
          If the resource has two public dimensions, use a composite public id
          such as "room|slot" or map to a dict with room and slot fields.
          For precedence schedules, use:
          {{"type": "precedence_schedule", "operations": [
            {{"id": op_id, "start_var": "start_<op>", "processing_time": p,
              "machine_vars": [{{"machine": m, "var": "assign_<op>_<m>"}}]}}
          ]}}
        - For small precedence/resource scheduling, a linear_mip model can use:
          start variables for operations, binary assignment variables for
          eligible resource choices, binary ordering variables for operation
          pairs that may share a resource, big-M non-overlap constraints,
          precedence constraints, and nonnegative tardiness variables. Use this
          pattern when the table size is small enough to emit a complete spec.
          For a tardiness variable T_op with finish=start_op+p and due=d,
          encode T_op >= start_op + p - d as coefficients
          {{"T_op": 1, "start_op": -1}}, sense ">=", rhs p-d.
          Do not reverse the sign.
        - Use solver_mode="moea" when the public optimization contract says
          objective_mode="multi_objective", or when the user explicitly asks
          for a Pareto front, trade-off set, or multiple objectives to optimize
          separately.
        - Otherwise, even if the problem has several soft terms such as
          preference, fairness, tardiness, distance, service, or disruption,
          set solver_mode="scalar_ga" and combine them into one scalar with
          public weights. Return objectives=[base_scalar].
        - For larger coverage plans, many-slot assignments, routing-like
          decisions, or preference-heavy schedules where a complete LP/MILP spec
          would be large or brittle, use solver_mode="scalar_ga" with compact
          segments.
        - For route sequencing with travel times, service order, or
          path-dependent costs, choose solver_mode="scalar_ga" unless the
          public optimization contract is multi_objective or you emit a
          complete numeric routing MILP. Do not use linear_mip for a partial
          assignment-only route model; represent the route with assignment plus
          permutation segments and compute travel/time penalties in fitness.py.
        - For coverage or quota requirements, it is often compact to expand
          required positions into anonymous demand slots in setup.py, then use
          assignment/optional_assignment and check one-assignment-per-resource
          or capacity constraints in fitness.py.
        - For fixed coverage planning, prefer expanding each
          required (day, shift, k) coverage position into a demand slot assigned
          to a staff member. This satisfies coverage by construction and leaves
          fitness.py to penalize duplicate staff-day assignments, max shifts,
          absences, preferences, and sequence rules. Avoid binary roster
          encodings unless you also implement a compact repair that restores
          coverage and one-shift-per-person-per-day.

        Public data summary:
        {table_summary or "(none; build_problem may read public_context directly)"}

        Available primitive skills:
        {skills or "real_vector, int_vector, binary_vector, permutation, choice_vector, assignment, optional_assignment"}

        Problem:
        {problem}

        {repair_feedback}

        Return exactly:
        ### setup.py
        ```python
        def build_problem(public_context):
            ...
        ```
        ### fitness.py
        ```python
        def evaluate(genome, data):
            ...
        ```
        """
    ).strip()


def _extract_prompt_tables(public_context: dict[str, Any]) -> dict[str, Any]:
    if isinstance(public_context.get("tables"), dict):
        return public_context["tables"]
    if isinstance(public_context.get("csv_tables"), dict):
        return public_context["csv_tables"]
    if isinstance(public_context.get("public_data"), dict):
        public_data = public_context["public_data"]
        if isinstance(public_data.get("tables"), dict):
            return public_data["tables"]
        if isinstance(public_data.get("csv_tables"), dict):
            return public_data["csv_tables"]
        return public_data
    return public_context


def _format_optimization_contract(contract: Any) -> str:
    if not isinstance(contract, dict) or not contract:
        return ""
    keys = [
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
        "auxiliary_metrics",
        "update_contract",
        "instruction",
    ]
    lines = []
    for key in keys:
        if key in contract:
            lines.append(f"- {key}: {_contract_value(contract[key])}")
    return "\n".join(lines)


def _public_prompt_contract(public_context: dict[str, Any]) -> dict[str, Any]:
    source = public_context.get("public_objective_spec")
    if isinstance(source, dict) and source:
        return source
    contract = public_context.get("optimization_contract")
    if not isinstance(contract, dict):
        return {}
    public_keys = {
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
        "auxiliary_metrics",
        "update_contract",
        "instruction",
    }
    return {key: value for key, value in contract.items() if key in public_keys}


def summarize_tables_for_prompt(data: dict[str, Any], *, max_rows: int = 3) -> str:
    lines: list[str] = []
    for table_name, rows in sorted(data.items()):
        if isinstance(rows, dict) and isinstance(rows.get("rows"), list):
            rows = rows["rows"]
        if not isinstance(rows, list):
            continue
        columns = sorted({str(key) for row in rows[: max_rows * 2] if isinstance(row, dict) for key in row.keys()})
        sample = rows[:max_rows]
        lines.append(f"- {table_name}: columns={columns}; sample={sample}")
    return "\n".join(lines)


def _public_scoring_text(public_context: dict[str, Any]) -> str:
    text = public_context.get("public_objective_spec_text")
    return str(text).strip() if isinstance(text, str) and text.strip() else ""


def _contract_value(value: Any) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)
