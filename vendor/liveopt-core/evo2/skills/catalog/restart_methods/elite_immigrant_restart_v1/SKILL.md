# Elite-Immigrant Restart

Skill ID: elite_immigrant_restart_v1
Skill Type: restart
Summary: Keep a controlled elite fraction from memory and fill the remaining population with fresh samples.
Planner Tags: restart, elite_transfer, immigrants, medium_update, strict_skill_match

## Use When
- Some old high-quality candidates remain informative but broad population reuse is risky.
- The public update is medium-scale, such as several changed resources or tighter public limits.

## Do Not Use When
- The update is tiny enough for warm restart or broad population transfer.
- The update is structurally incompatible with previous encoding.

## Required Public Evidence
- Elite candidates and current public feasibility diagnostics.
- Transfer ratio chosen from public change scale.

## Required Artifact Fields
- previous_population or archive ranks.
- encoding_spec, repair_operator, verifier.

## Operating Procedure
- Select a bounded fraction of prior elites or nondominated representatives.
- Repair and verify elites under current public constraints.
- Fill the rest of the population with immigrant samples from the current encoding.
- Record elite fraction, immigrant fraction, and rejected elite reasons.

## Selection Checklist
- Some prior high-quality candidates remain informative, but broad transfer is risky.
- The update is medium-scale and changes several resources, limits, or public objective weights.
- Encoding compatibility is unchanged.

## Prompt Guidance
- Use a conservative transfer ratio when feasibility is uncertain.
- Keep more immigrants when new constraints remove many old feasible regions.
- Do not collapse the whole population to one elite; preserve search diversity.

## Minimal Example
- Example: "several server capacities and priorities changed" -> selected_restart_skill=elite_immigrant_restart_v1, transfer_ratio=0.2.

## Output Contract
- Return elite repaired seeds and fresh random immigrants.

## Failure Mode
- If no elite candidates remain public-feasible after repair, fail and choose a named diversity/full restart.
