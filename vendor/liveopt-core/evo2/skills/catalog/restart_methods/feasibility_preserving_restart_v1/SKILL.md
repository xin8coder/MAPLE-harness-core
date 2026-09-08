# Feasibility-Preserving Restart

Skill ID: feasibility_preserving_restart_v1
Skill Type: restart
Summary: Repair previous candidates against current public constraints before seeding search.
Planner Tags: restart, feasibility, repair_seed, dynamic_update, strict_skill_match

## Use When
- A public update may invalidate feasibility but the same solution structure remains meaningful.
- The repair operator can enforce the changed public rows without changing the generated decode interface.

## Do Not Use When
- The update changes the task type, solution schema, or encoding.
- The previous population uses incompatible public decision ids.

## Required Public Evidence
- Changed public rows and affected constraint categories.
- Compatible generated decode and repair artifacts.

## Required Artifact Fields
- previous_solution or previous_population.
- repair_operator and verifier.

## Operating Procedure
- Take previous solution/front/population candidates that match the current encoding signature.
- Run repair_operator before objective-driven search and reject seeds that still fail the public verifier.
- Keep repaired feasible seeds and fill missing slots with standard current-encoding samples.
- Record which public constraints were repaired and how many seeds survived.

## Selection Checklist
- A public update changes constraints more than objectives, but the solution schema is stable.
- Previous candidates may be invalid but still encode useful structure.
- The repair operator has explicit logic for the changed constraint category.

## Prompt Guidance
- Choose this skill for capacity, availability, eligibility, or required/blocked changes when ids remain compatible.
- Pair it with ga_or_moea when feasibility repair should be followed by search.
- Escalate to diversity_restart_v1 if most repaired seeds fail.

## Minimal Example
- Example: "two machines become unavailable" -> selected_restart_skill=feasibility_preserving_restart_v1 with repaired prior placements.

## Output Contract
- Return feasibility-repaired seeds with public violation diagnostics.

## Failure Mode
- If compatibility cannot be certified, fail and choose a named full or diversity restart.
