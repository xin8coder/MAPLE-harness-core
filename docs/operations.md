# MAPLE Harness

## Application identity

The deployed product is **MAPLE Harness: Agent Harness for Live
Optimization**. Its sidebar mark, empty-session
hero, browser title, and favicon use the MAPLE identity; the upstream DeepSeek
mark is not used as the application's primary brand. The sidebar's **About
MAPLE Harness** dialog records the application version and identifies DeepSeek Harness
as the MIT-licensed host. The upstream copyright, license, and dependency notices
remain part of the distribution.

This package integrates the MAPLE optimization runtime with a conversational application. It imports the existing `evo2` TSS/LSM implementation as a dependency and exposes public-data preparation, asynchronous optimization, silent waiting, inspection, and result export through MCP. The plugin imports the core runtime as a dependency.

The standalone public repository includes a pinned source snapshot under
`vendor/liveopt-core/`. The installer prefers that snapshot, while this
monorepo copy continues to resolve the research checkout directly. Set
`LIVEOPT_CORE_ROOT` to test the Harness against another explicit MAPLE core
revision.

## Reproducibility isolation

The plugin is deliberately outside the standalone execution path:

- The adapter, MCP schemas, DSH bundle, tests, and deployment files live only under ``.
- Installation copies `evo2/`, `demo/`, and the adapter sources into a disposable build directory before producing wheel snapshots. Setuptools cannot leave `build/` or `*.egg-info` products in the research checkout.
- The installed sidecar uses its own virtual environment and writes sessions, provider traces, and response caches under `LIVEOPT_MCP_STATE_DIR` (default: `~/.local/share/liveopt-dsh`), never under the benchmark output directories.
- Provider/cache environment variables are set inside the sidecar process only. Existing `DEEPSEEK_CACHE_DIR`, `KIMI_CACHE_DIR`, and trace settings are deliberately ignored so a terminal configured for benchmark runs cannot mix the two artifact sets. Optional path overrides must use the `LIVEOPT_MCP_*` namespace.
- The container mounts the public-data workspace read-only. Its writable state is a separate named volume.
- `tests/test_isolation.py` guards these boundaries. The original core commands remain unchanged and do not import `liveopt_dsh`.

Thus the plugin consumes a snapshot of the core implementation, while standalone evaluation remains governed by the original root package, experiment commands, caches, and frozen artifacts.

## Architecture

```text
DeepSeek Harness
  -> bundled MAPLE data, solve, and result skills
  -> compact MAPLE MCP tools
  -> local stdio Python sidecar
  -> existing MAPLE Workbench / TSS / LSM / restart runtime
  -> atomic session snapshots, turn traces, and provider response caches
```

`start` and `update` return immediately with a job id. Harness then enters one `wait` tool call and remains silent until the job completes. The browser progress card reads a local read-only status endpoint, so it updates without repeated model turns. The accepted Workbench, public context, full population/archive, and public update ledger are saved after each successful transition. Restarting the sidecar reconstructs the executable Workbench and continues from that accepted state.

The web profile also loads dedicated data, progress, and result cards through DSH's keyed Tool-view extension point. During evolutionary search, the progress card shows the current phase, generation, feasible population count, archive size, population size, and elapsed time. On an update, it reports the selected Full, Warm, or Population Transfer action and reused-solution count as soon as restart seeds are built, before search begins. Exact LP/MILP runs show their formulation/solver phase and elapsed time. The result card renders one panel per objective with best, population mean, and population range trajectories; it also shows the final population distribution with Pareto solutions highlighted and provides CSV, JSON, and ZIP downloads. Complete visual data is loaded from the authenticated sidecar result endpoint, so a large second-turn population is not truncated in the MCP transcript. Collection and presentation are sidecar-only and do not alter core entrypoints.

The conversation surface has a dedicated **Solutions** view beside Chat and Trajectory. It follows the conversation selected in Harness automatically, with no second session selector. MAPLE tool results bind each conversation to its persisted optimization session, and the view switches to that session's accepted turns, original requirement or update, restart/reuse decision, objective traces, final population and Pareto set, solution preview, deterministic conclusion, TSS encoding segments and code slots, public data patch, validation summary, and downloadable artifacts. This view reads the atomic event log; it does not infer state from assistant prose.

The application exposes one mode only. It disables DSH's model, permission, preset, and plan selectors; fixes the host and sidecar to `deepseek-v4-flash`; and continuously enforces the light theme. The focused **MAPLE Settings** page stores the DeepSeek key in Harness' owner-only credential document and controls the default evolutionary iteration count (100 unless changed). Test-only injected clients remain available to the adapter unit suite without network access.

## Requirements

- Python 3.10 or newer.
- Node.js `22.19+` and DeepSeek Harness `0.1.0-rc.8`. The local bootstrap pins Node.js `24.19.0` so DSH can honor standard proxy environment variables through `NODE_USE_ENV_PROXY=1`.
- A DeepSeek API key entered in **MAPLE Settings** or supplied once through `DEEPSEEK_API_KEY` at launch. A launch-time key is migrated to Harness' owner-only credential store and removed from the child-process environment. The application fixes both the Harness host and every MAPLE agent role to `deepseek-v4-flash`; Pro models are not selectable.

The versions are pinned because DeepSeek Harness is currently a release candidate and its plugin API may change.

## Local installation

The repository also contains a provider-free project page under `site/`. Its
interactive CNC case explorer is generated from accepted Harness exports and
shows the natural-language sequence, restart choices, objective traces, final
population, Pareto set, representative schedule, and sanitized TSS artifacts.
GitHub Pages deploys only this static directory; it never receives executable
code, credentials, application state, or provider traces.

For a machine without Node.js or DeepSeek Harness, the no-sudo bootstrap installs pinned Node.js, pnpm, DSH, the MAPLE wheel snapshot, and the bundle entirely under the current user's home directory:

```bash
scripts/bootstrap_local.sh
```

Start the local web profile after exporting a provider key:

```bash
export DEEPSEEK_API_KEY=...
export LIVEOPT_MCP_WORKSPACE_ROOT=/path/to/public/data/workspace
scripts/start_local.sh
```

The default UI address is `http://127.0.0.1:3000`. For an SSH host, forward port 3000 in the local editor. `LIVEOPT_ENV_FILE=/path/to/env` may be used to load a private environment file at startup. Its DeepSeek key is migrated to `~/.dsh/.credentials.yaml` with mode `0600`; unrelated environment values are not copied into plugin state.

`LIVEOPT_MCP_NETWORK_MODE=auto` is the default. It uses the shell HTTPS proxy when one is configured and otherwise connects directly. Set it to `direct` or `system_proxy` to force either transport. This setting applies only inside the plugin sidecar.

### First real task

Open the web UI and give Harness both the natural-language request and public data. For example:

```text
Use LiveOpt to select items with maximum total value. Total selected weight must
not exceed the public capacity. Return selected item ids, total value, and total
weight. The public items are I1(value 10, weight 4), I2(8, 5), I3(6, 3), and
I4(5, 2); capacity is 8. Preserve the LiveOpt session id for later updates.
```

After the initial job succeeds, continue in the same conversation:

```text
The public capacity is now 6 instead of 8. Keep all item records unchanged and
update the existing LiveOpt session rather than starting over.
```

Harness will call `liveopt_start` once and then hold one `liveopt_wait` call while the progress card refreshes independently. Later requirements use `liveopt_update` followed by the same silent wait. The accepted TSS Workbench, LSM state, search population/archive, raw provider responses, and both transitions remain available through `liveopt_inspect`.

When a public problem supports more than one route, the user may select `exact` for an LP/MILP backend, `evolutionary` for scalar GA or Pareto NSGA-II, or `auto` for MAPLE to choose. This choice is passed to Workbench construction before code generation. Exact application runs have an interactive time limit (30 seconds by default); a time-limited incumbent is accepted only after generic bounds, integrality, and linear-constraint verification.

### Existing Node.js installation

From the repository root:

```bash
scripts/install.sh
```

The installer creates an isolated virtual environment under `~/.local/share/liveopt-dsh/runtime`, writes `~/.local/bin/liveopt-mcp`, and adds the prebuilt JavaScript bundle to the `web` DSH profile. It installs a wheel snapshot of the current MAPLE checkout; it does not edit or wrap the core entrypoints.

Then configure the DeepSeek key and start Harness:

```bash
export DEEPSEEK_API_KEY=...
export LIVEOPT_MCP_WORKSPACE_ROOT=/path/to/public/data/workspace
dsh --profile web
```

Use `LIVEOPT_DSH_PROFILE=headless` during installation to target the headless profile. Set `LIVEOPT_MCP_COMMAND` if the sidecar executable lives somewhere other than `~/.local/bin/liveopt-mcp`.

## Intranet deployment

DeepSeek Harness intentionally refuses a direct `0.0.0.0` bind because its tools can execute code. The intranet launcher therefore keeps DSH on loopback and exposes it through an HTTPS reverse proxy bound only to the detected RFC1918 address:

```bash
scripts/bootstrap_intranet.sh
LIVEOPT_ENV_FILE=/path/to/private.env \
  scripts/start_intranet.sh
```

The default public port is `3000`, while DSH remains on `127.0.0.1:3001`. The private endpoint does not require an application username or password. Caddy uses a local CA; import `~/.local/share/liveopt-dsh/caddy-data/caddy/pki/authorities/local/root.crt` on trusted clients, or accept the browser warning during private testing. Do not forward this endpoint outside the trusted intranet.

### Persistent background service

Install the user-level systemd unit so MAPLE starts after reboot and is not
tied to an SSH or VS Code terminal:

```bash
./scripts/install_systemd_user.sh
sudo loginctl enable-linger "$USER"
```

Useful service commands:

```bash
systemctl --user status liveopt-intranet.service
journalctl --user -u liveopt-intranet.service -f
systemctl --user restart liveopt-intranet.service
```

If the host requires an outbound proxy, the installer records the current
`HTTPS_PROXY` value in the owner-only
`~/.config/liveopt-dsh/service.env`. This keeps API access independent of the
terminal environment used to start the service.

## MCP tools

| Tool | Purpose |
|---|---|
| `liveopt_prepare_data` | Convert public CSV, TSV, JSON, or JSONL files to typed record tables and return a compact data id. |
| `liveopt_prepare_uploads` | Combine browser-uploaded CSV/TSV/JSON/JSONL/XLSX tables and TXT/Markdown/PDF/DOCX documents into one public context. |
| `liveopt_start` | Build the initial TSS Workbench with `auto`, `exact`, or `evolutionary` solving and return session/job ids. |
| `liveopt_update` | Apply one natural-language update to an existing LSM state. Returns a job id. |
| `liveopt_override_slots` | Validate user-edited setup/fitness slots and continue the same session after bounded automatic repair fails. |
| `liveopt_wait` | Hold one silent tool call until a job is terminal while the UI refreshes progress independently. |
| `liveopt_inspect` | Read job status, compact accepted state, Workbench, artifact paths, or a turn trace. |
| `liveopt_export` | Write solution, final-population, and iteration CSVs, a JSON bundle, and a ZIP archive, then return a visual preview. |
| `liveopt_cancel` | Cancel work that is still queued. Running transitions are atomic and are not killed midway. |

The tools are grouped by the three user actions: prepare public data, solve or update, and export accepted results. Detailed prompts, raw responses, code slots, data patches, and restart evidence remain available through `inspect` rather than separate schemas.

### Browser document upload

The web plugin adds a **Document** control to the question composer. It accepts up to 12 files per selection and uploads them to the MAPLE sidecar before submission. The composer inserts a compact `[MAPLE upload: ...; id=...]` reference into the same question; the bundled skill resolves all referenced ids with one `liveopt_prepare_uploads` call and passes the returned `prepared_data_id` to `liveopt_start`. No server path or document body is copied into chat.

Uploads are immutable, checksum-verified, and stored under the application state directory rather than the source checkout. The default per-file limit is 25 MiB (`LIVEOPT_MCP_MAX_UPLOAD_BYTES`). Extracted prose is bounded by `LIVEOPT_MCP_MAX_DOCUMENT_CHARS` (120,000 characters by default), and truncation is reported in the preparation card. Uploaded prose is treated only as public problem context; embedded macros, scripts, and instructions are never executed.

## Dynamic update resilience

The application path keeps mutable resources in public tables. `liveopt_prepare_data` can combine file-backed and inline public records, and its optional `column_groups` transform turns repeated wide columns into a generic source/entity association table. Generated Workbench slots are instructed to derive domains and lookup maps from those rows rather than embedding entity IDs or per-entity column tuples. A row addition, removal, activation, or parameter change can therefore use the structured JSON data-patch path; recompiling the unchanged slot source rebuilds the current search domain.

When source code really must change, the application patcher requests one JSON object whose values are raw Python slot strings. Its compatibility parser also accepts older fenced responses, removes nested fence lines, and performs an AST syntax check before execution. Repair feedback names the failing slot, line, column, and source line. If bounded automatic repair still fails, `liveopt_override_slots` accepts a user-edited setup and/or fitness slot, validates it, reuses the compatible accepted population, and commits the repaired Workbench in the same session. These behaviors are implemented only in the application sidecar and do not modify standalone evaluation code.

## Persistence and cache behavior

The default state root is `~/.local/share/liveopt-dsh/state`:

```text
sessions/<session_id>/snapshot.json      accepted TSS/LSM state
sessions/<session_id>/events/*.json      full per-turn prompts and artifacts
jobs/<job_id>.json                       durable asynchronous job status
cache/{deepseek,semantic_restart}/       response caches
provider_traces/                         provider request metadata
application_settings.json                non-secret UI defaults, including iterations
```

The default `LIVEOPT_MCP_CACHE_MODE=read_write` checks provider caches before every request and stores new responses. `cache_only` blocks cache misses, and `off` disables response and semantic-choice caches. API keys are never accepted as MCP arguments and are never saved in snapshots, jobs, or application settings; they live only in Harness' `0600` credential document.

If the process stops during a job, the last accepted session snapshot remains authoritative and the job is marked `interrupted`. Resubmit the same `session_id`/`update_id`: completed updates are idempotent, while incomplete provider calls reuse their response cache.

## Public data boundary

`liveopt_start` accepts either an inline `public_context` object or a JSON `public_context_path`. Paths are resolved beneath `LIVEOPT_MCP_WORKSPACE_ROOT`; traversal outside that root is rejected. Hidden evaluators, hidden reference fronts, and benchmark-only contracts are not exposed through the plugin.

Generated Workbench slots are executable Python, just as in the core implementation. For untrusted users, run the combined container instead of the sidecar directly:

```bash
docker compose -f docker-compose.yml up --build
```

The combined container keeps stdio transport internal, persists state in a named volume, and avoids opening a separate MCP port. Mount only the public-data workspace that MAPLE should read.

## Verification

Python and MCP tests:

```bash
python -m venv /tmp/liveopt-dsh-test
/tmp/liveopt-dsh-test/bin/pip install ./vendor/liveopt-core . pytest
/tmp/liveopt-dsh-test/bin/python -m pytest tests -q
```

`test_offline_requirement_matrix.py` uses an API-shaped, prompt-driven local DeepSeek simulator and blocks network access. It runs the complete service path for healthcare MILP selection, retail integer inventory, cold-chain permutation routing, continuous bi-objective microgrid dispatch, binary public-budget selection, and mixed assignment/permutation CNC scheduling. The CNC case also disables one public machine through a data-only natural-language update and verifies that no setup or fitness source is regenerated.

With `dsh`, `liveopt-mcp`, and Node.js on `PATH`, the following executes a complete no-provider Harness -> MCP tool-call round trip against a local OpenAI-compatible mock:

```bash
scripts/smoke_dsh.sh
```
