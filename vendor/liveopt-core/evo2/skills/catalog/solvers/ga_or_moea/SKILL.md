# GA or MOEA Solver

Skill ID: ga_or_moea
Skill Type: solver
Summary: Run single- or multi-objective evolutionary search over Workbench-generated data, decoding, repair, and fitness slots with LiveOpt-owned typed operators.
Planner Tags: solver, ga, moea, nsga2, evolutionary_search, public_verifier, strict_skill_match

## Use When
- The task is combinatorial, routing-like, scheduling-like, assignment-like, nonlinear, multi-objective, or uses a generated public verifier/objective.
- A complete Workbench setup, decode, repair, and fitness interface can be materialized from selected skills.
- The LP/MILP skill lacks a complete public model or solution_extraction.

## Do Not Use When
- The selected encoding/operator skill or generated decode artifact is absent.
- The verifier/objective cannot consume the decoded canonical solution.
- A deterministic exact solver is explicitly required and a complete public LP/MILP spec is available.

## Required Public Evidence
- Public decision units and any resources, capacities, time windows, costs, coordinates, or precedence fields used by generated artifacts.
- Objective terms and hard constraints stated in the public request or public objective specification.
- Encoding family and compatible operator skill.

## Required Artifact Fields
- `solver_mode` is `scalar_ga` or `moea`.
- Workbench slots include `setup.py`, `decode.py`, `repair.py`, and `fitness.py`.
- Segment kinds and restart skill are compatible with the selected TSS setup.

## Operating Procedure
- Select exactly one encoding family: permutation for ordered decisions, int/binary for assignment or selection, or real_vector for continuous public parameters.
- Let the executor inject the standard crossover and mutation for the selected operator family; do not generate stub operators.
- Decode every genome into the canonical solution schema, repair hard public violations, verify feasibility, then evaluate objective values.
- For multi-objective stages, return objective dicts with scalar, objectives, objective_names, and diagnostics so the archive can be scored.
- On dynamic stages, select a restart skill from public change scale and memory compatibility before search starts.

## Selection Checklist
- The problem is multi-objective, nonlinear, routing-like, scheduling-like, assignment-like, or black-box under a public verifier.
- A public decode artifact, repair operator, verifier, and objective can be made consistent with the same canonical solution schema.
- LP/MILP is incomplete, too restrictive, or cannot represent the public objective/constraints.

## Prompt Guidance
- Name the chosen search-space, solver, and restart skills in the Workbench setup or planner note.
- Keep genome shape stable across dynamic updates unless the public task type or encoding truly changes.
- Use population_transfer_v1 for compatible multi-objective fronts, warm_restart_v1 for local changes, and diversity/full restart for structural changes.

## Minimal Example
- Example: "multi-objective green routing with distance and emissions" -> primary_solver=ga_or_moea, operator=ea_encoding_permutation_order_v1, restart=warm_restart_v1 when ids remain compatible and public repair remains useful; switch to full_restart_v1 only when the runtime landscape probe shows a regime reset.

## Output Contract
- Return the best feasible solution or Pareto archive under the public verifier.
- Report population/archive metadata, hidden-free feasibility diagnostics, budget, and selected restart policy.

## Failure Mode
- If no explicit encoding/operator skill is selected, fail validation and request a new generic encoding primitive or operator skill.
