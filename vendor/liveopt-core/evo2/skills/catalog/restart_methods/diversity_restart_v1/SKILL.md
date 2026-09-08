# Diversity Restart

Skill ID: diversity_restart_v1
Skill Type: restart
Summary: Seed search with diverse repaired representatives and fresh samples after large public shifts or objective-trade-off changes.
Planner Tags: restart, diversity, exploration, large_update, strict_skill_match

## Use When
- Public changes alter the feasible region or objective trade-offs enough that old elites may be misleading.
- A few previous diverse representatives may still help coverage but should not dominate the new population.
- The encoding and public ids remain broadly compatible, but the planner needs more exploration than warm_restart_v1 or population_transfer_v1 would provide.
- The old front is partly stale but still likely covers useful regions after re-ranking under the current public objective.
- Several small public updates have accumulated and warm_restart_v1 risks over-anchoring on a previous-best neighborhood, but some repaired historical representatives may still be useful.

## Do Not Use When
- The public update is local and old best/front candidates remain reliable.
- A single local update leaves both the old best and archive diversity clearly reliable.
- Encoding compatibility cannot be established.
- The previous Pareto archive is broad, repairable, and still likely useful; prefer warm_restart_v1 as the default repaired-reuse policy.
- The update is structurally incompatible or flips the objective/search geometry so old representatives are expected to seed the wrong basin; use full_restart_v1.

## Required Public Evidence
- Change-scale rationale from public update semantics.
- Diversity representatives or archive spread metadata if reused.

## Required Artifact Fields
- previous_population or archive if available.
- encoding_spec and repair_operator.

## Operating Procedure
- Sample diverse representatives from previous archive regions when compatible.
- Repair representatives, keep only public-verifier-compatible seeds, and add many fresh samples.
- Bias seeds toward different objective regions, resource groups, or route/schedule structures when public data supports it.
- Record the public change-scale reason and diversity source.

## Selection Checklist
- Public objectives or constraints changed enough that old elites may mislead search.
- Accumulated local objective or policy edits make a compact warm neighborhood risky.
- Some old representatives may still help, but exploration should dominate.
- The task remains in the same broad encoding family.
- Public reasoning supports partial reuse rather than a clean break from memory.

## Prompt Guidance
- Use this skill for large public shifts that still permit partial memory use.
- Prefer it over full_restart_v1 when compatible ids remain and a previous archive exists.
- Do not over-trust old objective ranks after objective trade-offs change.
- For multi-objective tasks, choose this over population_transfer_v1 only when transferred archive regions are expected to be stale or too narrow.
- Choose full_restart_v1 instead when a public regime flip changes the objective geometry so strongly that prior regions are misleading, not just under-ranked.

## Minimal Example
- Example: "new sustainability objective and changed vehicle limits" -> selected_restart_skill=diversity_restart_v1.

## Output Contract
- Return diverse repaired seeds plus fresh exploration samples.

## Failure Mode
- If no compatible representatives exist, use the named full_restart_v1 skill.
