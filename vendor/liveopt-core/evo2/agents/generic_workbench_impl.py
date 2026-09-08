from __future__ import annotations

import ast
import copy
import json
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from evo2.agents.llm_client import create_llm_client, is_llm_quota_limit_error
from evo2.agents.liveopt_workbench_impl import ScaffoldProject, ScaffoldTrace, normalize_scaffold_public_context
from evo2.agents.liveopt_workbench_impl import _compile_slot
from evo2.core.template_optimizer import (
    Candidate,
    EvolutionConfig,
    EvolutionResult,
    GenericEvolutionHooks,
    coerce_fitness_result,
    run_generic_evolution,
)


GENERIC_WORKBENCH_FUNCTIONS = (
    "build_state",
    "initialize",
    "evaluate_decode",
    "crossover",
    "mutate",
    "coerce_repair",
)


@dataclass
class GenericWorkbenchProject:
    task_id: str
    public_context: dict[str, Any]
    state: dict[str, Any]
    artifact_code: str
    hooks: GenericEvolutionHooks
    problem_spec: dict[str, Any]
    trace: ScaffoldTrace

    @property
    def setup_code(self) -> str:
        return self.artifact_code

    @property
    def fitness_code(self) -> str:
        return self.artifact_code

    @property
    def segments(self) -> list[Any]:
        return []

    def run(
        self,
        config: EvolutionConfig | None = None,
        *,
        initial_candidates: list[dict[str, Any]] | None = None,
        initial_genomes: list[dict[str, Any]] | None = None,
    ) -> EvolutionResult:
        if initial_candidates is not None and initial_genomes is not None:
            raise ValueError("pass only one of initial_candidates or initial_genomes")
        return run_generic_evolution(
            self.hooks,
            state=self.state,
            config=config,
            initial_candidates=initial_candidates if initial_candidates is not None else initial_genomes,
        )


def compile_generic_workbench(
    task_id: str,
    public_context: dict[str, Any],
    artifact_code: str,
    *,
    smoke_test: bool = True,
    trace: ScaffoldTrace | None = None,
) -> GenericWorkbenchProject:
    """Compile a complete untyped artifact without the TSS segment palette."""

    _validate_generic_artifact_source(artifact_code)
    public_context = normalize_scaffold_public_context(public_context)
    functions: dict[str, Callable[..., Any]] = {
        name: _compile_slot(artifact_code, name) for name in GENERIC_WORKBENCH_FUNCTIONS
    }
    state = functions["build_state"](copy.deepcopy(public_context))
    if not isinstance(state, dict):
        raise ValueError("generic Workbench build_state(public_context) must return a dict")
    problem_spec = dict(state.get("problem_spec") or {})
    if not problem_spec:
        objective_names = list(state.get("objective_names") or [])
        problem_spec = {
            "solver_mode": "moea" if len(objective_names) > 1 else "scalar_ga",
            "sense": "min",
            "objective_names": objective_names,
        }
    hooks = GenericEvolutionHooks(
        initialize=functions["initialize"],
        evaluate_decode=functions["evaluate_decode"],
        crossover=functions["crossover"],
        mutate=functions["mutate"],
        coerce_repair=functions["coerce_repair"],
    )
    project = GenericWorkbenchProject(
        task_id=task_id,
        public_context=copy.deepcopy(public_context),
        state=state,
        artifact_code=artifact_code,
        hooks=hooks,
        problem_spec=problem_spec,
        trace=trace or ScaffoldTrace(model="generic_compiled"),
    )
    _validate_generic_public_contract(project, public_context)
    if smoke_test:
        smoke_result = project.run(
            EvolutionConfig(
                population_size=6,
                generations=1,
                archive_limit=6,
                seed=0,
                structured_initialization=False,
            )
        )
        _validate_generic_smoke_result(project, smoke_result, public_context)
    return project


class GenericWorkbenchPatcher:
    """Patch one persistent ordinary artifact from public updates only."""

    prompt_version = "liveopt_without_tss_patch_v1"

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)

    def patch_project(
        self,
        *,
        task_id: str,
        artifact_code: str,
        natural_language_update: str,
        public_context: dict[str, Any],
        max_repairs: int = 3,
    ) -> GenericWorkbenchProject:
        trace = ScaffoldTrace(model=self.model)
        previous_error = ""
        current_code = artifact_code
        started = time.perf_counter()
        for attempt in range(max(1, int(max_repairs) + 1)):
            prompt = build_generic_workbench_patch_prompt(
                artifact_code=current_code,
                natural_language_update=natural_language_update,
                public_context=public_context,
                previous_error=previous_error,
            )
            trace.prompts.append(prompt)
            response = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Patch a persistent ordinary Python optimization artifact. "
                            "Return exactly one complete python code block and no prose."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=8000,
            )
            trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(response, dict) else ""
            trace.raw_responses.append(content)
            try:
                current_code = extract_python_artifact(content)
                project = compile_generic_workbench(
                    task_id,
                    public_context,
                    current_code,
                    smoke_test=True,
                    trace=trace,
                )
                trace.latency_seconds = time.perf_counter() - started
                project.trace = trace
                return project
            except Exception as exc:  # noqa: BLE001
                if is_llm_quota_limit_error(exc):
                    raise
                previous_error = f"{type(exc).__name__}: {exc}"
                trace.errors.append(previous_error)
                if attempt >= max_repairs:
                    trace.latency_seconds = time.perf_counter() - started
                    raise ValueError("Generic Workbench patch repair failed: " + previous_error) from exc
        raise ValueError("Generic Workbench patch failed without producing an artifact")


class GenericWorkbenchBuilder:
    """Generate an untyped Workbench from the public problem and bare callback ABI.

    Unlike :func:`generic_artifact_from_scaffold`, this builder receives no TSS
    slots, segment declarations, encoded candidates, or operator suggestions.
    The model must choose its representation and variation/repair logic from
    the public task itself.
    """

    prompt_version = "liveopt_without_tss_from_scratch_v1"

    def __init__(self, model: str = "deepseek-v4-pro", client: Any | None = None):
        self.model = model
        self.client = client or create_llm_client(model=model)

    def build_project(
        self,
        *,
        task_id: str,
        public_problem: str,
        public_context: dict[str, Any],
        max_repairs: int = 3,
    ) -> GenericWorkbenchProject:
        trace = ScaffoldTrace(model=self.model)
        previous_error = ""
        previous_code = ""
        started = time.perf_counter()
        for attempt in range(max(1, int(max_repairs) + 1)):
            prompt = build_generic_workbench_from_scratch_prompt(
                public_problem=public_problem,
                public_context=public_context,
                previous_error=previous_error,
                previous_code=previous_code,
            )
            trace.prompts.append(prompt)
            response = self.client.chat(
                [
                    {
                        "role": "system",
                        "content": (
                            "Implement an optimization artifact from a public problem using only a bare "
                            "callback ABI. Return exactly one complete python code block and no prose."
                        ),
                    },
                    {"role": "user", "content": prompt},
                ],
                temperature=0.0,
                max_tokens=8000,
            )
            trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
            content = response.get("choices", [{}])[0].get("message", {}).get("content", "") if isinstance(response, dict) else ""
            trace.raw_responses.append(content)
            try:
                previous_code = extract_python_artifact(content)
                project = compile_generic_workbench(
                    task_id,
                    public_context,
                    previous_code,
                    smoke_test=True,
                    trace=trace,
                )
                trace.latency_seconds = time.perf_counter() - started
                project.trace = trace
                return project
            except Exception as exc:  # noqa: BLE001
                if is_llm_quota_limit_error(exc):
                    raise
                previous_error = f"{type(exc).__name__}: {exc}"
                trace.errors.append(previous_error)
                if attempt >= max_repairs:
                    trace.latency_seconds = time.perf_counter() - started
                    raise ValueError("Generic Workbench from-scratch build failed: " + previous_error) from exc
        raise ValueError("Generic Workbench from-scratch build failed without producing an artifact")


def generic_artifact_from_scaffold(project: ScaffoldProject) -> str:
    """Materialize the accepted t00 scaffold as ordinary, artifact-owned hooks.

    The generated module owns concrete representation and variation functions.
    At runtime it never constructs ``SegmentSpec`` objects or calls the typed
    operator palette. Dynamic semantic changes are patched on this ordinary
    module by :class:`GenericWorkbenchPatcher`.
    """

    if not project.segments:
        raise ValueError("generic conversion requires at least one evolutionary segment")
    state_lines = [
        "    problem = build_problem(public_context)",
        "    state = {'data': problem['data'], 'problem_spec': {k: v for k, v in problem.items() if k not in ('data', 'segments')}}",
    ]
    init_lines = ["    candidate = {}"]
    cross_lines = ["    child = {}"]
    mutate_lines = ["    child = {k: (dict(v) if isinstance(v, dict) else list(v) if isinstance(v, list) else v) for k, v in candidate.items()}"]
    repair_lines = ["    repaired = {}"]
    for index, segment in enumerate(project.segments):
        name = repr(str(segment.name))
        prefix = f"s{index}"
        if segment.kind in {"assignment", "optional_assignment"}:
            allow_none = bool(segment.allow_none or segment.kind == "optional_assignment")
            state_lines.extend(
                [
                    f"    {prefix} = next(s for s in problem['segments'] if s.get('name') == {name})",
                    f"    state[{name} + '_demands'] = list({prefix}.get('demands') or [])",
                    f"    state[{name} + '_resources'] = list({prefix}.get('resources') or [])",
                    f"    state[{name} + '_allow_none'] = {allow_none!r}",
                ]
            )
            init_lines.extend(
                [
                    f"    demands = state[{name} + '_demands']",
                    f"    resources = state[{name} + '_resources']",
                    f"    options = resources + ([None] if state[{name} + '_allow_none'] else [])",
                    f"    candidate[{name}] = {{d: rng.choice(options) for d in demands}}",
                ]
            )
            cross_lines.extend(
                [
                    f"    demands = state[{name} + '_demands']",
                    f"    a = parent_a.get({name}, {{}})",
                    f"    b = parent_b.get({name}, {{}})",
                    f"    child[{name}] = {{d: (a.get(d) if rng.random() < 0.5 else b.get(d)) for d in demands}}",
                ]
            )
            mutate_lines.extend(
                [
                    f"    demands = state[{name} + '_demands']",
                    f"    resources = state[{name} + '_resources']",
                    f"    options = resources + ([None] if state[{name} + '_allow_none'] else [])",
                    f"    values = dict(child.get({name}, {{}}))",
                    f"    if demands and options: values[rng.choice(demands)] = rng.choice(options)",
                    f"    child[{name}] = values",
                ]
            )
            repair_lines.extend(
                [
                    f"    demands = state[{name} + '_demands']",
                    f"    resources = state[{name} + '_resources']",
                    f"    options = resources + ([None] if state[{name} + '_allow_none'] else [])",
                    f"    old = old_candidate.get({name}, {{}})",
                    f"    repaired[{name}] = {{d: (old.get(d) if old.get(d) in options else rng.choice(options)) for d in demands}}",
                ]
            )
        elif segment.kind == "permutation":
            state_lines.extend(
                [
                    f"    {prefix} = next(s for s in problem['segments'] if s.get('name') == {name})",
                    f"    state[{name} + '_values'] = list({prefix}.get('values') or [])",
                ]
            )
            init_lines.extend(
                [
                    f"    values = list(state[{name} + '_values'])",
                    "    rng.shuffle(values)",
                    f"    candidate[{name}] = values",
                ]
            )
            cross_lines.extend(
                [
                    f"    values = list(state[{name} + '_values'])",
                    f"    a = [x for x in parent_a.get({name}, []) if x in values]",
                    f"    b = [x for x in parent_b.get({name}, []) if x in values]",
                    "    cut = rng.randrange(len(values) + 1) if values else 0",
                    "    prefix_values = a[:cut]",
                    "    remaining_values = []",
                    "    for x in b + values:",
                    "        if x in values and x not in prefix_values and x not in remaining_values:",
                    "            remaining_values.append(x)",
                    f"    child[{name}] = prefix_values + remaining_values",
                ]
            )
            mutate_lines.extend(
                [
                    f"    values = list(child.get({name}, []))",
                    "    if len(values) > 1:",
                    "        i = rng.randrange(len(values))",
                    "        j = rng.randrange(len(values))",
                    "        values[i], values[j] = values[j], values[i]",
                    f"    child[{name}] = values",
                ]
            )
            repair_lines.extend(
                [
                    f"    allowed = list(state[{name} + '_values'])",
                    f"    kept = [x for x in old_candidate.get({name}, []) if x in allowed]",
                    "    kept = list(dict.fromkeys(kept))",
                    "    missing = [x for x in allowed if x not in kept]",
                    "    rng.shuffle(missing)",
                    f"    repaired[{name}] = kept + missing",
                ]
            )
        elif segment.kind == "binary_vector":
            state_lines.extend(
                [
                    f"    {prefix} = next(s for s in problem['segments'] if s.get('name') == {name})",
                    f"    state[{name} + '_length'] = int({prefix}.get('length') or 0)",
                ]
            )
            init_lines.extend(
                [
                    f"    length = state[{name} + '_length']",
                    f"    candidate[{name}] = [rng.randrange(2) for _ in range(length)]",
                ]
            )
            cross_lines.extend(
                [
                    f"    length = state[{name} + '_length']",
                    f"    a = list(parent_a.get({name}, []))",
                    f"    b = list(parent_b.get({name}, []))",
                    f"    child[{name}] = [int((a[i] if i < len(a) else 0) if rng.random() < 0.5 else (b[i] if i < len(b) else 0)) != 0 for i in range(length)]",
                ]
            )
            mutate_lines.extend(
                [
                    f"    length = state[{name} + '_length']",
                    f"    values = [1 if int(x) != 0 else 0 for x in list(child.get({name}, []))[:length]]",
                    "    values += [0] * max(0, length - len(values))",
                    "    if length:",
                    "        i = rng.randrange(length)",
                    "        values[i] = 1 - values[i]",
                    f"    child[{name}] = values",
                ]
            )
            repair_lines.extend(
                [
                    f"    length = state[{name} + '_length']",
                    f"    values = [1 if int(x) != 0 else 0 for x in list(old_candidate.get({name}, []))[:length]]",
                    "    values += [0] * max(0, length - len(values))",
                    f"    repaired[{name}] = values",
                ]
            )
        else:
            raise ValueError(f"unsupported generic conversion segment kind: {segment.kind}")
    for segment in project.segments:
        gate = (segment.metadata or {}).get("resource_open_gate") if isinstance(segment.metadata, dict) else None
        if not isinstance(gate, dict) or not gate.get("segment"):
            continue
        assignment_name = repr(str(segment.name))
        gate_name = repr(str(gate["segment"]))
        open_value = int(gate.get("open_value", 1))
        for lines, variable in (
            (init_lines, "candidate"),
            (cross_lines, "child"),
            (mutate_lines, "child"),
            (repair_lines, "repaired"),
        ):
            lines.extend(
                [
                    f"    gate_resources = state[{assignment_name} + '_resources']",
                    f"    gate_values = list({variable}.get({gate_name}, []))",
                    "    gate_values += [0] * max(0, len(gate_resources) - len(gate_values))",
                    f"    for assigned_resource in {variable}.get({assignment_name}, {{}}).values():",
                    "        if assigned_resource in gate_resources:",
                    f"            gate_values[gate_resources.index(assigned_resource)] = {open_value}",
                    f"    {variable}[{gate_name}] = gate_values",
                ]
            )
    state_lines.append("    return state")
    init_lines.append("    return candidate")
    cross_lines.append("    return child")
    mutate_lines.append("    return child")
    repair_lines.append("    return repaired")
    sections = [
        project.setup_code.strip(),
        project.fitness_code.strip(),
        "def build_state(public_context):\n" + "\n".join(state_lines),
        "def initialize(state, rng):\n" + "\n".join(init_lines),
        "def evaluate_decode(candidate, state):\n    return evaluate(candidate, state['data'])",
        "def crossover(parent_a, parent_b, state, rng):\n" + "\n".join(cross_lines),
        "def mutate(candidate, state, rng):\n" + "\n".join(mutate_lines),
        "def coerce_repair(old_candidate, state, rng):\n" + "\n".join(repair_lines),
    ]
    return "\n\n".join(sections) + "\n"


def build_generic_workbench_patch_prompt(
    *,
    artifact_code: str,
    natural_language_update: str,
    public_context: dict[str, Any],
    previous_error: str = "",
) -> str:
    normalized = normalize_scaffold_public_context(public_context)
    error_block = f"\nPrevious compile/smoke error:\n{previous_error}\n" if previous_error else ""
    return f"""You maintain a persistent ordinary Python optimization artifact.

Public update:
{natural_language_update}

Updated public context (no hidden or reference data):
{json.dumps(normalized, ensure_ascii=False, sort_keys=True)}

Current complete artifact:
```python
{artifact_code}
```
{error_block}
Return one complete replacement artifact in exactly one ```python block.
Preserve unchanged public semantics and patch only what the update requires.
The artifact must define build_state(public_context), initialize(state, rng),
evaluate_decode(candidate, state), crossover(parent_a, parent_b, state, rng),
mutate(candidate, state, rng), and coerce_repair(old_candidate, state, rng).
It may define helper functions but may not import anything, use SegmentSpec or
typed operator/selection/archive APIs, read hidden/reference data, or implement
selection, archive maintenance, early stopping, or the outer evolutionary loop.
All IDs and values must be derived from public_context; do not hard-code episode IDs.
"""


def build_generic_workbench_from_scratch_prompt(
    *,
    public_problem: str,
    public_context: dict[str, Any],
    previous_error: str = "",
    previous_code: str = "",
) -> str:
    """Expose only public task data and the minimum executable callback ABI."""

    normalized = normalize_scaffold_public_context(public_context)
    repair_block = ""
    if previous_error:
        repair_block = f"""
The preceding attempt failed compilation or public smoke validation:
{previous_error}

Repair this preceding attempt without adding hidden assumptions:
```python
{previous_code}
```
"""
    return f"""Build a complete persistent Python optimization artifact from scratch.

Public natural-language problem:
{public_problem}

Public context (no hidden or reference data):
{json.dumps(normalized, ensure_ascii=False, sort_keys=True)}

Only the following bare framework contract is provided. No encoding template,
candidate-field schema, operator palette, initialization strategy, crossover
strategy, mutation strategy, or repair strategy is supplied.

Return one complete artifact in exactly one ```python block. It must define:
- build_state(public_context) -> dict
- initialize(state, rng) -> candidate dict
- evaluate_decode(candidate, state) -> a dict with scalar, objectives,
  feasible, violations, solution, and optional diagnostics
- crossover(parent_a, parent_b, state, rng) -> candidate dict
- mutate(candidate, state, rng) -> candidate dict
- coerce_repair(old_candidate, state, rng) -> candidate dict

Choose the candidate representation and every operator yourself from the public
problem. build_state must include problem_spec with solver_mode, sense, and the
public objective_names. Objective values must follow the public minimization
contract. coerce_repair must accept either this artifact's earlier candidate or
a decoded public solution from the common predecessor population and encode it
into the representation chosen here.

The artifact may define helper functions but may not import anything, use
SegmentSpec, call typed operator/selection/archive APIs, read hidden/reference
data, or implement selection, archive maintenance, early stopping, restart
selection, or the outer evolutionary loop. The execution environment supplies
ordinary Python builtins, math, and the rng argument. Derive all IDs, values,
dimensions, objectives, and constraints from public_context; do not hard-code
episode IDs.
{repair_block}"""


def extract_python_artifact(content: str) -> str:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("empty Generic Workbench response")
    matches = re.findall(r"```(?:python)?\s*(.*?)```", content, flags=re.IGNORECASE | re.DOTALL)
    if len(matches) != 1:
        raise ValueError(f"expected exactly one python code block, got {len(matches)}")
    code = matches[0].strip()
    if not code:
        raise ValueError("empty Generic Workbench code block")
    return code + "\n"


def generic_restart_seeds(
    *,
    project: GenericWorkbenchProject,
    previous_result: EvolutionResult | None,
    restart_skill: str,
    population_size: int,
    seed: int,
    decoded_solution_transfer: bool = False,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if restart_skill == "full_restart_v1" or previous_result is None:
        return [], {
            "restart_skill": restart_skill,
            "source": "fresh_generic_artifact",
            "seed_count": 0,
            "fresh_population_ratio": 1.0,
            "history_population_ratio": 0.0,
            "workbench_interface": (
                "generic_blank_callbacks_v1" if decoded_solution_transfer else "generic_operator_hooks_v1"
            ),
            "source_transfer_kind": (
                "none_full_restart" if decoded_solution_transfer else "none"
            ),
        }
    if restart_skill != "warm_restart_v1":
        raise ValueError(f"unsupported Generic Workbench restart: {restart_skill}")
    rng = random.Random(seed)
    candidates = list(previous_result.population or []) + list(previous_result.archive or [])
    target = max(1, min(int(population_size), int(population_size) // 2))
    seeds: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            old_candidate = candidate.genome
            if decoded_solution_transfer:
                solution = candidate.result.solution if candidate.result is not None else None
                if not isinstance(solution, dict) or not solution:
                    continue
                old_candidate = solution
            genome = project.hooks.coerce_repair(copy.deepcopy(old_candidate), project.state, rng)
            result = coerce_fitness_result(project.hooks.evaluate_decode(copy.deepcopy(genome), project.state), genome)
        except Exception:
            continue
        if not result.feasible:
            continue
        key = json.dumps(genome, ensure_ascii=False, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(genome)
        if len(seeds) >= target:
            break
    return seeds, {
        "restart_skill": restart_skill,
        "source": "generic_coerce_from_previous_population",
        "seed_count": len(seeds),
        "previous_candidate_count": len(candidates),
        "fresh_population_ratio": 1.0 - len(seeds) / max(1, int(population_size)),
        "history_population_ratio": len(seeds) / max(1, int(population_size)),
        "workbench_interface": (
            "generic_blank_callbacks_v1" if decoded_solution_transfer else "generic_operator_hooks_v1"
        ),
        "source_transfer_kind": (
            "decoded_public_solution_reencoding" if decoded_solution_transfer else "encoded_candidate_coercion"
        ),
    }


def _validate_generic_artifact_source(code: str) -> None:
    if not isinstance(code, str) or not code.strip():
        raise ValueError("generic Workbench artifact is empty")
    tree = ast.parse(code)
    if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in ast.walk(tree)):
        raise ValueError("generic Workbench artifact may not import modules")
    forbidden = {"SegmentSpec", "run_evolution", "run_generic_evolution", "nsga2_select"}
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used = sorted(forbidden & names)
    if used:
        raise ValueError("generic Workbench may not call typed/driver internals: " + ", ".join(used))
    defined = {node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}
    missing = [name for name in GENERIC_WORKBENCH_FUNCTIONS if name not in defined]
    if missing:
        raise ValueError("generic Workbench missing hooks: " + ", ".join(missing))


def _validate_generic_public_contract(project: GenericWorkbenchProject, public_context: dict[str, Any]) -> None:
    contract = public_context.get("optimization_contract") if isinstance(public_context, dict) else None
    if not isinstance(contract, dict):
        return
    if str(contract.get("objective_mode") or "") != "multi_objective":
        return
    expected = [str(item) for item in contract.get("objective_names") or []]
    actual = [str(item) for item in project.problem_spec.get("objective_names") or []]
    if project.problem_spec.get("solver_mode") != "moea":
        raise ValueError("Generic Workbench multi-objective contract requires solver_mode='moea'")
    if actual != expected:
        raise ValueError(f"Generic Workbench objective names {actual!r} do not match public contract {expected!r}")


def _validate_generic_smoke_result(
    project: GenericWorkbenchProject,
    result: EvolutionResult,
    public_context: dict[str, Any],
) -> None:
    contract = public_context.get("optimization_contract") if isinstance(public_context, dict) else None
    if not isinstance(contract, dict) or str(contract.get("objective_mode") or "") != "multi_objective":
        return
    expected_dim = len(contract.get("objective_names") or [])
    candidates = list(result.population or []) + list(result.archive or [])
    if not candidates:
        raise ValueError("Generic Workbench smoke test returned no candidates")
    for candidate in candidates[:8]:
        objectives = list(candidate.result.objectives if candidate.result else [])
        if len(objectives) != expected_dim:
            raise ValueError(
                f"Generic Workbench returned {len(objectives)} objectives; public contract requires {expected_dim}"
            )
