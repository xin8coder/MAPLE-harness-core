# Full Restart

Skill ID: full_restart_v1
Skill Type: restart
Summary: Shock-response policy. Discard previous search seeds and initialize the full population from the current typed space only when verified public evidence supports a severe representation, objective-dimension, or feasibility break.
Planner Tags: restart, full_random, structural_change, strict_skill_match

## Use When
- The public update changes the decision schema, encoding, or generated solution interface.
- Previous candidates cannot be mapped to current public decision ids.
- Public ids, active entity sets, eligibility relations, resource universes, or hard feasibility rules change so substantially that most transferred candidates would be structurally invalid.
- Verified public evidence shows a severe loss of historical feasibility under the current representation.
- The public update explicitly changes the optimization task type or required solution schema.
- Many small public updates have accumulated, the current archived population is narrow, and public reasoning suggests old seeds may keep the search in a stale basin even though the encoding remains compatible.
- A scalar or rugged search landscape has repeated soft-objective edits and no reliable diverse archive to transfer; a fresh current-encoding search is needed to re-test the objective landscape.

## Do Not Use When
- Previous solution or population can be repaired and remains informative.
- Previous solution or population remains both repairable and diverse enough to explore the current public objective.
- The update only changes small objective weights, soft penalties, priorities, due/SLA targets, energy/carbon prices, emissions, or other coefficients and the previous archive is still expected to cover the new front.
- The text sounds like a "regime change" but does not identify a changed public field and a supported failure mechanism; use warm_restart_v1.
- Quality is low merely because the current population needs more search; restart selection cannot use hidden quality metrics.

## Required Public Evidence
- Incompatibility reason based on public schema, public ids, or selected skill changes.
- A cited changed public field, a supported break mechanism, and high reported risk under the fixed evidence rule.

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
- The objective dimension or typed representation changed, or verified public evidence supports severe historical infeasibility.
- If only minor soft objectives or trade-off weights changed and warm repair remains feasible/useful, this checklist is not satisfied.
- If only one minor soft objective changed and the repaired archive is still informative, this checklist is not satisfied.
- If many minor soft changes have accumulated and the archive is narrow or repeatedly anchored, this checklist may be satisfied even without an encoding change.

## Prompt Guidance
- Use this skill explicitly and sparingly; it is the correct answer to structural incompatibility.
- Pair with ga_or_moea unless a complete exact public solver is selected.
- Do not call this merely because quality is low; quality-only issues need more search or a different solver.
- Do not call this merely because the natural-language update uses words such as "reset", "regime", "wave", or "policy"; first check whether the encoding and hard feasible region truly became incompatible.
- For updates that keep the same typed representation and objective dimension without verified severe feasibility loss, use warm_restart_v1.

## Minimal Example
- Example: "the problem changes from selecting projects to assigning jobs to machines" -> selected_restart_skill=full_restart_v1.
- Example: "the depot/reference frame and cost economics are reset, so the old route/front geometry is misleading although the same orders remain active" -> selected_restart_skill=full_restart_v1.

## Output Contract
- Return a fresh initialized population.

## Failure Mode
- If current encoding cannot be built, fail validation and request the missing generic encoding primitive or operator skill.
