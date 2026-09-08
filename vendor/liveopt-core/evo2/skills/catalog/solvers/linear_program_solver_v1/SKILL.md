# Linear Program Solver

Skill ID: linear_program_solver_v1
Skill Type: solver
Summary: Solve a public LP/MILP only when the LLM-generated artifact layer provides a complete linear_program_spec.
Planner Tags: solver, exact, lp, milp, public_model, strict_skill_match

## Use When
- The prompt or generated artifact layer provides a complete linear_program_spec with variables, objective coefficients, constraints, integrality, and solution_extraction.
- The public solver profile explicitly requests an exact solver and the task is scalar and linearly representable.

## Do Not Use When
- No complete linear_program_spec is provided.
- The task has black-box objectives, nonlinear feasibility, multi-objective trade-offs, routing-like sequence costs, or generated decode-only objectives.
- The only reason to choose LP is that the problem is "small"; small combinatorial problems still require a valid LP/MILP model.

## Required Public Evidence
- Public table names and column roles used by the generated model.
- Objective direction and numeric coefficients or a deterministic public coefficient construction.
- Every hard constraint has public numeric rows, bounds, and senses.
- solution_extraction maps solver variables back to the public solution schema.

## Required Artifact Fields
- solver_recommendation.primary_solver = "linear_program_solver_v1".
- linear_program_spec.
- solution_extraction in the LP/MILP spec.

## Operating Procedure
- Build variables with explicit public names, types, lower bounds, and upper bounds.
- Build objective coefficients and each constraint coefficient from public numeric table fields or deterministic public derivations.
- Include solution_extraction that maps solver variables back to selected_decisions, placements, schedule fields, or another canonical public solution.
- After solving, reconstruct the canonical solution and run the same public verifier used by other solvers.

## Selection Checklist
- All objective coefficients, constraint senses, right-hand sides, and variable domains are known before solver execution.
- The task is scalar or can be converted to a stated scalar public objective without hiding trade-offs.
- The LLM emitted a complete linear_program_spec.

## Prompt Guidance
- Do not use symbolic stand-ins such as value[i], sum over rows, or "for each item" in the emitted spec.
- If a coefficient is missing from public data, choose ga_or_moea or fail validation rather than inventing a private coefficient.
- Keep solver choice fixed after selection; do not silently switch solvers inside runtime.

## Minimal Example
- Example: "binary knapsack with public value, weight, and budget" -> binary variables x_item, objective=sum public value*x, constraint=sum public weight*x<=budget.

## Output Contract
- Return solver_values and a canonical public solution reconstructed from solution_extraction.
- Report objective_value, status, bounds, gap, and backend metadata.

## Failure Mode
- If the model spec is missing or incomplete, fail validation. Do not switch to another solver inside the executor.
