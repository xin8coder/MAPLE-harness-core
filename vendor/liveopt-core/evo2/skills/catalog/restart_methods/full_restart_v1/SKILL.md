# Full Restart

Skill ID: full_restart_v1
Skill Type: restart
Summary: Last-resort shock response policy. Discard previous population and initialize from the current public encoding only when runtime probing shows that prior candidates cannot be safely mapped, repaired, or used as informative seeds under the current public problem.
Planner Tags: restart, full_random, structural_change, strict_skill_match

## Use When
- The public update changes the decision schema, encoding, or generated solution interface.
- Previous candidates cannot be mapped to current public decision ids.
- Public ids, active entity sets, eligibility relations, resource universes, or hard feasibility rules change so substantially that most transferred candidates would be structurally invalid.
- The public update keeps ids compatible, but public runtime probing shows that direct migration and repair are both weak while fresh current-encoding samples are viable and better.
- The public update explicitly changes the optimization task type or required solution schema.
- Many small public updates have accumulated, the current archived population is narrow, and public reasoning suggests old seeds may keep the search in a stale basin even though the encoding remains compatible.
- A scalar or rugged search landscape has repeated soft-objective edits and no reliable diverse archive to transfer; a fresh current-encoding search is needed to re-test the objective landscape.

## Do Not Use When
- Previous solution or population can be repaired and remains informative.
- Previous solution or population remains both repairable and diverse enough to explore the current public objective.
- The update only changes small objective weights, soft penalties, priorities, due/SLA targets, energy/carbon prices, emissions, or other coefficients and the previous archive is still expected to cover the new front.
- The text sounds like a "regime change" but cheap public reasoning indicates old archive regions remain useful; use population_transfer_v1 or warm_restart_v1 according to the skill cards.
- Quality is low merely because the current population needs more search diversity; keep the choice between warm_restart_v1, population_transfer_v1, and full_restart_v1 grounded in the public update, not hidden quality.

## Required Public Evidence
- Incompatibility reason based on public schema, public ids, or selected skill changes.
- Public landscape-probe evidence that repair/projection of previous candidates would be invalid or misleading in the current feasibility or objective landscape, not just worse-scoring.

## Required Artifact Fields
- Current encoding_spec and genome sampler.

## Operating Procedure
- Discard previous solution/population seeds for initialization.
- Build all initial individuals from the current encoding_spec and public tables.
- Keep memory only as audit context for why reuse was rejected, not as transferred seeds.
- Record the public incompatibility reason.

## Selection Checklist
- Generated solution interface, encoding family, or public id universe changed.
- Prior candidates cannot be projected into the current canonical schema.
- Public hard constraints or active decision sets changed enough that repaired memory would bias search toward invalid regions.
- Public objective geometry changed enough that old Pareto regions are expected to pull search toward the wrong basin/front region, and public probing confirms that repair/transfer is not useful.
- If only minor soft objectives or trade-off weights changed and warm repair remains feasible/useful, this checklist is not satisfied.
- If only one minor soft objective changed and the repaired archive is still informative, this checklist is not satisfied.
- If many minor soft changes have accumulated and the archive is narrow or repeatedly anchored, this checklist may be satisfied even without an encoding change.

## Prompt Guidance
- Use this skill explicitly and sparingly; it is the correct answer to structural incompatibility.
- Pair with ga_or_moea unless a complete exact public solver is selected.
- Do not call this merely because quality is low; quality-only issues need more search or a different solver.
- Do not call this merely because the natural-language update uses words such as "reset", "regime", "wave", or "policy"; first check whether the encoding and hard feasible region truly became incompatible.
- For multi-objective updates that keep the same decision ids and hard feasibility rules, prefer population_transfer_v1 or warm_restart_v1 when the old archive remains feasible or repairable; use full_restart_v1 only when public probing rejects both reuse paths.

## Minimal Example
- Example: "the problem changes from selecting projects to assigning jobs to machines" -> selected_restart_skill=full_restart_v1.
- Example: "the depot/reference frame and cost economics are reset, so the old route/front geometry is misleading although the same orders remain active" -> selected_restart_skill=full_restart_v1.

## Output Contract
- Return a fresh initialized population.

## Failure Mode
- If current encoding cannot be built, fail validation and request the missing generic encoding primitive or operator skill.
