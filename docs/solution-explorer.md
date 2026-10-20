# Solution Explorer

The application result card and each Solutions turn now have an **Explore and
select a plan** action. It opens a separate window. The interface follows the
current English/Chinese setting and can change language independently.

## Data and Selection

- Reads the complete saved `result_bundle.json` final population and archive,
  not the capped result previews. Latest-turn snapshots are a fallback.
- Deduplicates equal genome/objectives/decoded-solution records. All retained
  decision-distinct candidates remain available even when objective values tie.
- Computes nondominance over all feasible retained candidates using the
  existing optimizer implementation and its minimization objective convention.
  The result is an empirical Pareto set, not a certified global optimum.
- Displays all objective dimensions in the detail pane and permits selecting
  the two chart axes. Single-objective runs use candidate index on the x axis.
- Incomplete historical archives are explicitly marked. Missing old populations
  are never replaced with current-turn data.
- Selecting a point or table row highlights the plan. Sorting, pagination,
  search, Pareto filtering, JSON and CSV downloads do not invoke the LLM.
- A saved preference is a separate `preferences/tNNN.json` file. It does not
  modify the accepted solution, population, archive or restart policy. Telling
  the agent to preserve that choice in a future optimization is a separate
  request; merely saving a preference does not impose new constraints.
- Plans with `order_plan` start/finish times have a schedule chart. Plans with
  `warehouse_plan` usage/capacity records have a capacity chart. Other solution
  structures remain visible in generic detail tables without inferred schedules.
- Generated `orders` arrays and keyed `teams` / `warehouses` records are also
  supported when their timing, staffing and capacity fields are explicit.
  Display aliases do not modify the original result downloads.

## API

Relative to the sidecar (under `/liveopt-api` in the intranet deployment):

- `GET /explorer/?session=<id>&turn=<n>&lang=zh`
- `GET /solution-options/<id>?turn=<n>`
- `POST /solution-preferences/<id>` with JSON `{"turn": 0, "candidate_id": "..."}`

Finite feasible candidates only may be saved. Candidate identity is stable
within the saved turn. No external CDN is required. ECharts and Lucide are
vendored with license notices. The application and local desktop wrapper are
separate from the paper's experiment code.
