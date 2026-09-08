# Typed Search-Space Scaffolding

Skill ID: typed_search_space_scaffold_v1
Skill Type: search_space
Summary: A Workbench search-space skill for decomposing public optimization requests into typed decision segments whose initialization, crossover, mutation, and repair hooks are owned by LiveOpt, while the LLM writes the public data adapter and fitness semantics.
Planner Tags: tss, search_space, compositional_encoding, public_only, dynamic_optimization

## Use When
- A user provides a natural-language optimization request with public data, public objectives, and public constraints.
- The problem may combine optional selection, assignment, ordering, scheduling priorities, resource choices, or continuous parameters.
- The solver needs reusable evolutionary operators rather than a hand-written one-off encoding.

## Do Not Use When
- The request requires hidden evaluator state, reference solutions, benchmark ids, or private data.
- The public request does not state enough objective, constraint, or data semantics for the LLM to write data and fitness slots.
- The user already provides a complete explicit mathematical model that should be sent directly to an exact solver.

## Required Public Evidence
- Public task text and public tables or structured parameters.
- Public objective directions, objective components, and hard or soft constraint semantics.
- Public decision entities, finite value sets, numeric bounds, ordering domains, or resource sets for every segment.

## Required Artifact Fields
- `setup.py` returns `data`, `segments`, `solver_mode`, `objective_names`, and `constraint_names`.
- Each segment has a stable `name`, a generic `kind`, and public values, dimensions, resources, demands, or bounds.
- `data_adapter.py`, `decode.py`, `repair.py`, and `fitness.py` implement problem-specific data access, decoding, repair, and objective/penalty semantics from public inputs.
- `solver_mode` is one of `linear_mip`, `scalar_ga`, or `moea`.

## Operating Procedure
- Read the natural-language request and public tables, then decide whether the problem is direct exact solving, scalar evolutionary search, or Pareto evolutionary search.
- Decompose the decision process into typed segments rather than writing a benchmark-specific genome.
- Use `binary_vector` for optional activation, `choice_vector` or `assignment` for categorical resource choices, `permutation` for ordering, `real_vector` for bounded continuous controls, and `optional_assignment` when some demand may remain unassigned with penalties.
- Keep segment names stable across dynamic updates when the public decision schema is compatible.
- Put all problem semantics in the generated Workbench slots; do not encode entity-specific rules, objective formulas, or hidden checks in the skill metadata.
- On dynamic updates, update only the affected Workbench slots when possible and let restart skills choose how to reuse the accepted search state.

## Selection Checklist
- Every segment can be initialized, mutated, and crossed over by generic LiveOpt operators.
- The generated decode and repair slots can reconstruct a complete public candidate solution from the genome.
- The generated fitness slot computes all objectives and penalties from public data only.
- No rule depends on benchmark family, problem id, hidden reference, or previous hidden feasibility.

## Prompt Guidance
- Explain why each segment exists and which public decision it controls.
- Prefer a typed composite genome over one flat vector when the public problem has mixed decisions.
- Prefer a single primitive segment when only one decision form is needed.
- If a new user problem needs an unsupported primitive, add a generic encoding primitive skill rather than a problem-specific implementation.
- If an exact model is suitable, ask the LLM to fill the Workbench exact-solver fields instead of forcing GA/NSGA-II.

## Minimal Example
- A request to choose projects, assign selected projects to teams, and tune budget split can use `binary_vector` for selection, `assignment` for team choice, and `real_vector` for split ratios under one TSS setup.

## Output Contract
- The planner selects a TSS setup and compatible solver/restart skills.
- The LLM emits Workbench slots, not a separate intermediate model.
- The runtime injects generic solver, restart, and typed-operator implementations.
- The execution path is natural language -> Workbench slots -> TSS segments -> exact/scalar/Pareto solver -> accepted state and live-state memory.

## Failure Mode
- If public data cannot support a complete generated Workbench interface, validation should fail and request more public data or a new generic primitive skill.
