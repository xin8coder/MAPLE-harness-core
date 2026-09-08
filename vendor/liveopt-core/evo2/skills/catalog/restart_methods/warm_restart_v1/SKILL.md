# Warm Restart

Skill ID: warm_restart_v1
Skill Type: restart
Summary: Default dynamic reuse policy. Seed search from repaired previous solutions or archive representatives whenever public probing shows that history remains repairable under the current runtime.
Planner Tags: restart, warm_start, previous_solution, small_update, strict_skill_match

## Use When
- Only a few public coefficients, demands, time windows, priorities, or availability fields changed.
- The previous best solution or front is expected to remain feasible or nearly feasible after repair.
- The encoding signature and generated decode artifact interface are unchanged.
- The update is a local data/parameter correction and public repair keeps old candidates usable.
- Runtime landscape probing does not show a structural reset, objective-dimension change, or strongly misleading old/new ranking.

## Do Not Use When
- Many decisions/resources changed, a binding hard constraint moved substantially, or objective trade-offs reversed.
- Coordinates, resource economics, or objective geometry flip enough that public probing shows repaired history is mostly unusable or misleading.
- The encoding schema changed.
- The update changes the generated solution interface or encoding schema.
- Runtime landscape probing shows that repaired history is mostly infeasible or strongly misleading; use full_restart_v1.
- The text describes a large compatible objective-space shift and public probing confirms that repaired seeds would anchor the search in a stale region.
- Several local updates have accumulated and the current search state is visibly concentrated around a narrow basin, even if each individual update looked small.
- A fresh or exploration-heavy restart is needed to test whether the accumulated public objective now prefers a different region.

## Required Public Evidence
- Evidence that changed rows are local relative to the current public state.
- Current generated decode artifact, encoding, and verifier are unchanged.

## Required Artifact Fields
- previous_solution or previous Pareto/archive representatives.
- repair_operator paired with the active generated decode interface.

## Operating Procedure
- Project the previous best or a few prior front representatives into the current encoding signature.
- Repair each seed against the current public verifier before inserting it into the initial population.
- Fill the remaining population with local variants and standard encoding samples.
- Record retained seed count, repaired feasibility, and the public reason for warm reuse.

## Selection Checklist
- Solution interface, encoding family, and public id universe are unchanged.
- The update changes a small number of public rows or scalar coefficients.
- The previous solution/front is expected to remain near feasible after repair.
- The previous best/front neighborhood is expected to remain near-optimal, not merely syntactically compatible.
- Repeated local updates have not accumulated enough to make the old best/front a misleading anchor.
- For multi-objective tasks, still start from warm_restart_v1 unless runtime probing shows that the repaired archive is misleading or unusable.

## Prompt Guidance
- Use this skill as the default dynamic restart response after public runtime probing.
- Set migration policy to best_transfer or a small partial_transfer ratio.
- Do not use hidden metric trends to justify the restart decision.
- Do not escalate to full_restart_v1 for local coefficient changes.
- Do not repeat warm_restart_v1 mechanically across a long sequence of small updates. If public probing shows that repaired seeds are misleading or mostly unusable, choose full_restart_v1.
- Population transfer is an explicit diagnostic/ablation skill; do not prefer it automatically over warm repair from feasibility alone.
- If a public update flips objective geometry or reference frames, do not infer full_restart_v1 from wording alone; choose full only when public probing shows repair and direct migration are not useful.

## Minimal Example
- Example: "one demand increases slightly" -> selected_restart_skill=warm_restart_v1, transfer_ratio=0.1 to 0.3.

## Output Contract
- Return repaired previous seeds plus local variants.

## Failure Mode
- If repaired seeds are mostly infeasible or low quality, the planner should choose a named broader restart skill.
