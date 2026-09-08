# Artifact Repair Solver

Skill ID: artifact_repair
Skill Type: solver
Summary: Apply the selected repair operator to an existing candidate when a public update only requires local feasibility restoration.
Planner Tags: solver, repair, low_cost, public_update, strict_skill_match

## Use When
- The previous candidate already uses the current solution schema.
- The public update is small and the repair_operator is explicitly designed for the active generated solution interface.
- The goal is a cheap feasibility repair before or instead of a population search.

## Do Not Use When
- The update changes the decision schema, objective family, hard-constraint family, or encoding.
- The previous candidate is absent or not expressed in the current canonical solution schema.
- A multi-objective archive or broader exploration is needed.

## Required Public Evidence
- The generated decode and repair artifacts are unchanged or explicitly updated for the same solution schema.
- The changed public rows are consumable by the existing repair_operator.

## Required Artifact Fields
- repair_operator.
- current_solution in the current schema.
- verifier and objective for post-repair validation.

## Operating Procedure
- Start from current_solution or the nearest compatible memory candidate in the active canonical schema.
- Apply repair_operator once, then verify with the public verifier and compute the public objective.
- Preserve unchanged decisions unless a public hard constraint or explicit update requires movement.
- Escalate to a named search solver when repaired feasibility or objective quality is not acceptable.

## Selection Checklist
- The update is local and the active decode artifact, encoding, and solution schema are unchanged.
- There is a previous solution in memory that can be projected into the current encoding.
- The repair_operator explicitly handles the changed public row or scalar parameter.

## Prompt Guidance
- Use this skill as a cheap first response, not as proof that global search is unnecessary.
- Report repaired fields, public violations, objective diagnostics, and why no broader solver was selected.
- Do not hide infeasibility; if public verification fails, return failure feedback for the repair channel.

## Minimal Example
- Example: "one server capacity changed; keep the prior assignment where feasible" -> solver_recommendation.primary_solver=artifact_repair.

## Output Contract
- Return the repaired candidate and validation feedback.

## Failure Mode
- If repair cannot certify feasibility under the public verifier, fail or escalate through the planner to a named search skill.
