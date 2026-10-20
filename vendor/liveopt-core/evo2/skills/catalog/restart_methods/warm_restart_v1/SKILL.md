# Warm Restart

Skill ID: warm_restart_v1
Skill Type: restart
Summary: Default dynamic reuse policy. Greedily repair historical candidates for at most half of the new population, then fill the remaining slots with fresh typed candidates.
Planner Tags: restart, warm_start, previous_solution, small_update, strict_skill_match

## Use When
- Only a few public coefficients, demands, time windows, priorities, or availability fields changed.
- The previous best solution or front is expected to remain feasible or nearly feasible after repair.
- The encoding signature and generated decode artifact interface are unchanged.
- The update is a local data/parameter correction and public repair keeps old candidates usable.
- The fixed evidence rule does not verify a severe representation, objective-dimension, or feasibility break.

## Do Not Use When
- Many decisions/resources changed, a binding hard constraint moved substantially, or objective trade-offs reversed.
- Coordinates, resource economics, or objective geometry flip enough that public probing shows repaired history is mostly unusable or misleading.
- The encoding schema changed.
- The update changes the generated solution interface or encoding schema.
- Verified public evidence supports a severe representation, objective-dimension, or feasibility break; use full_restart_v1.
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
- Project previous population/archive representatives into the current typed segments.
- Greedily repair historical candidates against the current evaluator until at most half of the population is seeded.
- Fill every remaining slot with fresh candidates from the current typed space.
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
- Do not use hidden metric trends to justify the restart decision.
- Do not escalate to full_restart_v1 for local coefficient changes.
- Do not infer full_restart_v1 from shock words alone; require the fixed evidence rule to verify the break.

## Minimal Example
- Example: "one demand increases slightly" -> selected_restart_skill=warm_restart_v1; repair up to half of the historical candidates and fill the rest freshly.

## Output Contract
- Return repaired historical seeds for at most half of the population; the runtime fills the remaining slots freshly.

## Failure Mode
- If verified public evidence establishes a severe break, choose full_restart_v1.
