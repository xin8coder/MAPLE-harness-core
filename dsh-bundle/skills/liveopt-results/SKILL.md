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
