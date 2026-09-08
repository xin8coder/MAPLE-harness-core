<div align="center">

# MAPLE Harness

**A workspace for optimization that continues across requests.**

Bring your data, inspect a solution, and revise the same problem in conversation.

[Try the demo](https://anonymous.4open.science/w/MAPLE-demo-review-F98B/) · [Optimization runtime](https://anonymous.4open.science/r/MAPLE00) · [Quick start](#quick-start) · [Operations guide](docs/operations.md)

![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![Interface MCP](https://img.shields.io/badge/Interface-MCP-334B60)
![License ISC](https://img.shields.io/badge/License-ISC-39857D)

</div>

MAPLE stands for **Memory-Augmented Planning with Language and Evolution**. Recorded walkthroughs and runtime identifiers retain the earlier LiveOpt name.

MAPLE Harness connects a conversational application to the MAPLE optimization runtime. Each accepted turn retains the executable Workbench, public data, solution, search population, and event history. A later request revises that session and produces an updated solution with visible progress and downloadable results.

## From request to revised solution

| | In the workspace |
|---|---|
| **1 · Bring the problem** | Describe objectives and constraints, then attach tables or documents. Prepared data is visible before solving. |
| **2 · Choose a search route** | Use exact LP/MILP, evolutionary GA/NSGA-II, or automatic selection for the formulation. |
| **3 · Follow the solve** | Progress cards show the current phase, generations, feasibility, and archive size. |
| **4 · Inspect the result** | Explore objective traces, population distributions, Pareto solutions, and the accepted plan in **Solutions**. |
| **5 · Continue in context** | Change a parameter, resource, or requirement in the same conversation. Inspect the restart decision and updated accepted state. |
| **6 · Take the outputs** | Export CSV, JSON, and ZIP artifacts for further analysis. |

## Quick start

The standalone application requires **Python 3.10+** and a **DeepSeek API key**. On Linux, the bootstrap installs the pinned Node.js, package manager, DeepSeek Harness host, and MAPLE sidecar under your user account.

Download this anonymous repository as a source archive and extract it into a directory named `MAPLE-harness-core`.

```bash
cd MAPLE-harness-core
./scripts/bootstrap_local.sh

mkdir -p public-data
export LIVEOPT_MCP_WORKSPACE_ROOT="$PWD/public-data"
./scripts/start_local.sh
```

Open **http://127.0.0.1:3000**, enter your key in **MAPLE Settings**, and start a conversation. The application uses `deepseek-v4-flash`; the default evolutionary iteration count is **100** and can be changed in Settings. Real solves use the configured provider. To explore without a key, open the [recorded demo](https://anonymous.4open.science/w/MAPLE-demo-review-F98B/).

Already have the required Node.js and host tools? Use [`scripts/install.sh`](scripts/install.sh). See the [operations guide](docs/operations.md) for pinned versions, Docker, SSH forwarding, private-network deployment, and persistent services.

### Try two consecutive requests

**Start with public data:**

> Select items to maximize total value. Capacity is 8. Items are I1 (value 10, weight 4), I2 (8, 5), I3 (6, 3), and I4 (5, 2). Return selected item IDs, total value, and total weight.

**Then update the same conversation:**

> Capacity is now 6. Keep the item records unchanged and revise the current solution.

The second request continues the accepted session. **Solutions** exposes the request, public-data patch, selected search action, objective traces, and resulting plan for each accepted turn.

## What is retained

| State | Purpose |
|---|---|
| Public tables and requests | Define the current task and its update history |
| TSS Workbench | Holds the executable decision declarations and evaluation functions |
| Accepted solutions | Supply the current plan and historical decision references |
| Population and archive | Supply reusable candidates for subsequent search |
| Validation and artifacts | Record accepted transitions and downloadable outputs |

The sidecar saves accepted state atomically and reconstructs the Workbench after a restart. The default state directory is `~/.local/share/liveopt-dsh/state`; [`docs/operations.md`](docs/operations.md#persistence-and-cache-behavior) explains recovery and cache modes.

## Architecture

```text
Conversation + uploaded public data
                 │
       MAPLE Harness workspace
          Chat · Solutions · Trajectory
                 │
           MAPLE MCP sidecar
                 │
    Workbench · TSS · LSM · numerical solvers
                 │
      Accepted state + exported artifacts
```

The standalone source repository vendors its core dependency in `vendor/liveopt-core/`, with provenance in `SOURCE_REVISION`. `LIVEOPT_CORE_ROOT` selects an explicit alternative checkout. The monorepo integration resolves the research checkout directly. Application state is stored in its own persistent directory.

| Directory | Role |
|---|---|
| [`src/liveopt_dsh/`](src/liveopt_dsh/) | MCP tools, persistent sessions, data preparation, and result endpoints |
| [`dsh-bundle/`](dsh-bundle/) | Browser cards, settings, and application skills |
| [`scripts/`](scripts/) | Installation, startup, deployment, and smoke checks |
| [`tests/`](tests/) | Sidecar, state, data, and interface checks |

## Deployment and development

Workbench slots execute Python. Run the application within an isolation boundary suited to its users and data; keep credentials in the host credential store. The [operations guide](docs/operations.md) documents state directories, supported uploads, network settings, recovery, and deployment commands.

Run the sidecar checks from a standalone checkout:

```bash
python -m pip install -e vendor/liveopt-core -e . pytest
python -m pytest tests -q
```

For monorepo development, use the corresponding installation and test commands in the operations guide. The [online demo](https://anonymous.4open.science/w/MAPLE-demo-review-F98B/) contains the static preview; executable application source lives in [MAPLE-harness-core](https://anonymous.4open.science/r/MAPLE-harness-core).

## License

MAPLE Harness is released under the [ISC License](LICENSE). The DeepSeek Harness host retains its MIT license and upstream notices.
