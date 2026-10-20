---
name: liveopt-results
description: Export and present an accepted LiveOpt solution set and iteration history as CSV, JSON, and ZIP files.
---

# LiveOpt Results

Use `mcp__liveopt__liveopt_export` after a LiveOpt start or update has completed successfully.

- Pass the accepted `session_id`; do not reconstruct results from chat text.
- Let the dedicated result card present per-objective iteration traces, the final population distribution, highlighted Pareto solutions, the solution-set preview, and download actions.
- The export contains `solutions.csv`, `final_population.csv`, `iteration_history.csv`, `result_bundle.json`, and `liveopt_results.zip`.
- Briefly explain feasibility, objective values, and solution-set size in the final response. Do not paste large genomes, archives, or CSV contents into the conversation.
- Exported files contain public solutions and search metrics only. Raw provider traces and private process configuration are not included.
- Match the user's language automatically. Mapped workbooks also export localized solution files and the reversible `field_mapping.json`; present those downloads first. Use original table headers and entity names in summaries, not internal schema aliases. Canonical raw result files remain available for reproducibility.
- If export reports `unmapped_result_fields`, infer labels for these actual result paths from the requirement and mapping, then call `liveopt_export` once more with `result_labels: {path: user_language_label}`. Do not translate entity identifiers (dictionary keys that are public IDs), change values, or replace original labels. Ask about genuinely ambiguous units instead of guessing. Labels are stored for this turn without modifying its solver state.
