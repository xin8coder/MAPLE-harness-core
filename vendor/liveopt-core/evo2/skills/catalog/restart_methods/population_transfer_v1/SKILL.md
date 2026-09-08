# Population Transfer

Skill ID: population_transfer_v1
Skill Type: restart
Summary: Pareto-memory reuse policy that directly migrates a broad previous population when encoding compatibility is unchanged and public probing shows that the old archive remains feasible and informative.
Planner Tags: restart, population_memory, pareto_memory, transfer, strict_skill_match

## Use When
- The encoding signature, generated solution interface, and public decision id universe remain compatible.
- Public runtime probing shows that previous population/archive candidates remain directly feasible under the current public verifier.
- Multi-objective search specifically needs to test whether preserving several old trade-off regions is beneficial.
- The update is small or medium and does not collapse the feasible region.
- The update changes objective weights, carbon/energy prices, priority weights, soft due/SLA targets, emissions, service times, or other public coefficients while keeping the same active decisions and hard feasibility rules, and the change is smooth enough that prior Pareto regions should still cover useful parts of the new front.
- The natural-language update describes a policy or objective-space change, public ids and feasibility remain compatible, and the experiment explicitly wants direct migration instead of greedy repair.

## Do Not Use When
- New public constraints make most previous candidates structurally invalid.
- The public update changes the decision schema, active entity set, or required solution format.
- A hard feasibility change removes or forbids a large fraction of previous assignments/routes/schedules and repair evidence is weak; use full_restart_v1.
- The previous archive is tiny, collapsed to a single region, or known to lack diversity; use warm_restart_v1 for default continuity or full_restart_v1 for fresh exploration.
- Public probing shows that old Pareto regions are structurally misleading rather than merely re-ranked; use warm_restart_v1 if repair helps, or full_restart_v1 only if reuse is not useful.

## Required Public Evidence
- Compatible encoding metadata and public decision ids.
- Previous population/archive with objective vectors or ranks.

## Required Artifact Fields
- previous_population or previous Pareto archive.
- repair_operator, verifier, and objective.

## Operating Procedure
- Check that the current encoding signature and public decision/resource ids match the previous population.
- Repair every transferred candidate under the current public verifier and retain feasible or near-feasible representatives.
- Preserve diverse objective-vector regions, not only the single best candidate.
- Fill unused slots with fresh current-encoding samples and record retained fraction.

## Selection Checklist
- Dynamic update is small or medium and does not change the generated solution interface or encoding family.
- In multi-objective stages, use this skill when public reset/reversal/flip/double/multiplier changes keep decision ids compatible and direct candidates remain feasible; let current evaluation re-rank the archive.
- Multi-objective trade-off regions from memory are still meaningful.
- Previous archive/population has enough diversity to seed more than one region.
- The public feasible region is mostly the same, even if the preferred objective region changes sharply.
- Previous candidates can be repaired/evaluated with current public tables without changing their decision ids.
- Public reasoning indicates that prior trade-off regions remain useful after re-ranking.

## Prompt Guidance
- Do not prefer this skill merely because an MOEA stage has compatible public ids; require direct public feasibility and compatible encoding evidence.
- Prefer this skill over full_restart_v1 when a multi-objective archive remains directly feasible, because it preserves trade-off diversity that a full restart may lose.
- Use partial_transfer when constraints tightened; use broad/full transfer for coefficient-only or soft-objective updates with compatible ids.
- Do not apply when a public update changes task type or invalidates most decision ids.
- Do not reject population transfer only because old objective ranks are stale; transfer candidates as diverse seeds, then re-rank them under the current objective.
- Do reject population transfer when the public update makes old regions structurally misleading rather than merely stale.

## Minimal Example
- Example: "emission weight changes but orders and vehicles remain" -> selected_restart_skill=population_transfer_v1, migration_policy=broad_transfer.
- Example: "energy price doubles and SLA priorities shift over the same jobs/machines" -> selected_restart_skill=population_transfer_v1.

## Output Contract
- Return repaired transferred population plus metadata about retained fraction and infeasible repairs.

## Failure Mode
- If transferred candidates fail public verification at high rate, fail and choose a named exploration-heavy restart.
