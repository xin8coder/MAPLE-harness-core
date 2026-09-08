# Typed Compositional Encoding

Skill ID: typed_compositional_encoding_v1
Skill Type: encoding_skill
Summary: Declare a genome as a named composition of primitive segments. The skill supplies the mapping from segment type to initialization, mutation, and crossover; the LLM still designs the problem-specific decode, verifier, objective, and repair logic.
Planner Tags: encoding, composite_encoding, segment_primitives, order_permutation, int_vector, binary, real_vector, public_only

## Use When
- One flat genome cannot faithfully represent the public decision process.
- The problem combines multiple decision forms, such as visit/order sequence, resource assignment, optional selection, and continuous policy or threshold parameters.
- Public constraints may make selecting or serving every active decision infeasible, so the search space needs an explicit selection/leftover choice together with assignment or ordering.
- The search space should expose separate segment roles so restart, repair, and population transfer can preserve the right structure.

## Do Not Use When
- A single primitive encoding is sufficient.
- The problem has exactly one int_vector, binary, real_vector, or order_permutation decision variable. Use the matching primitive operator skill instead.
- The segment roles cannot be derived from public decision variables.
- You intend to hide a benchmark-specific decode implementation inside the skill. Decoding remains an artifact designed from the public contract.

## Required Public Evidence
- A public explanation of every segment's decision role.
- For each segment, public values or bounds.
- For opaque IDs, use the public table IDs as values and preserve them as strings.
- For numeric segments, provide explicit lower_bounds and upper_bounds.
- The upstream TSS Workbench setup must list the same segment names, primitive encodings, and public evidence sources.

## Required Artifact Fields
- encoding_spec returns {"encoding": "composite", "segments": [...], "metadata": {"operator_skill_id": "ea_encoding_composite_v1"}}.
- Every segment has name, role, encoding, and either values or dimension/bounds.
- Supported segment encodings are order_permutation, int_vector, binary, and real_vector.
- decode consumes solution["genome"] or raw genome as a dict keyed by segment name.
- repair_operator must preserve the same segment keys and segment-compatible genome shapes.

## Operating Procedure
- Read the Workbench `segments` list as the source of truth for segment names and primitive types.
- Decompose the public problem into primitive decisions.
- If decomposition yields exactly one primitive decision, do not use this composite skill; keep a flat primitive encoding and select the matching operator skill.
- Use order_permutation for ordered visits, priorities, schedules, or insertion order.
- Use int_vector for bounded categorical assignment choices.
- Use binary for optional activation/selection decisions.
- Use real_vector for continuous thresholds, mixture weights, split ratios, or policy parameters.
- For selection-plus-assignment or selection-plus-ordering, use a binary selection segment together with an assignment/order segment, or add an explicit unassigned sentinel to the assignment segment.
- For hard demand-count or slot-filling constraints, include a segment that represents required slots, slot-resource choices, or assignable slot rows; do not encode only a resource list unless the generated decode/repair artifacts deterministically expand it into complete required demand.
- For decisions with ordered time intervals, the generated solution should expose numeric start and end/finish values for each decision, even if the genome stores only order or resource choices.
- For repeated resource-period assignments, the generated solution should expose a flat resource-period mapping or assignment_rows list in addition to any nested convenience map.
- Keep segment names semantic, for example decision_order, resource_choice, open_mask, split_ratio, policy_weights.
- Build decode from the combination of segments and public constraints.
- Keep generated segments aligned with the TSS setup. If the setup uses binary, int_vector, real_vector, permutation, choice_vector, assignment, or optional_assignment, the executable solver state must expose the same primitive.

## Selection Checklist
- No segment is keyed by benchmark id, problem id, hidden reference, or entity-specific code.
- The segment list is enough to reconstruct the full candidate solution.
- Mutation/crossover can act independently on each segment without breaking its primitive type.
- Objective and verifier operate on decoded solution fields, not directly on hidden evaluator data.

## Prompt Guidance
- Explain why each segment is needed and what public decision variable it controls.
- Prefer fewer, semantically meaningful segments over many arbitrary numeric knobs.
- For assignment problems, int_vector may encode candidate resource indices, while order_permutation can encode insertion or repair order.
- For optional assignment problems, do not force every active decision into a finite resource with only one int_vector; include a selection mask or unassigned option so repair can find feasible subsets.
- For routing/visiting problems, order_permutation can encode visit order, while real_vector can encode continuous timing or policy choices when public bounds exist.
- For hard demand-count or repeated slot assignments, prefer composite segments over a single resource permutation so repair can fill every required slot before objective optimization.
- For mixed problems, combine segments instead of forcing all decisions into one int_vector.

## Minimal Example
- Composite assignment/order/control genome:
  {"encoding":"composite","segments":[{"name":"visit_order","role":"order of public stops","encoding":"order_permutation","values":["A","B","C"]},{"name":"vehicle_choice","role":"resource index for each stop","encoding":"int_vector","dimension":3,"lower_bounds":[0,0,0],"upper_bounds":[1,1,1]},{"name":"service_slack","role":"continuous timing slack","encoding":"real_vector","dimension":3,"lower_bounds":[0,0,0],"upper_bounds":[1,1,1]}],"metadata":{"operator_skill_id":"ea_encoding_composite_v1"}}

## Output Contract
- Runtime initializes a dict genome with one entry per segment.
- Runtime mutation/crossover applies the classical primitive operator segment-wise.
- LLM-authored decode/repair/verifier/objective define the problem semantics.
- The skill does not generate objective, verifier, repair, or decode logic; those are generated by the LLM from the public request and Workbench data.

## Failure Mode
- If decode cannot map the segment composition to a complete public solution without hidden or benchmark-specific logic, validation should fail and the encoding design must be revised.
