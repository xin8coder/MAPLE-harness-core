# MAPLE Harness Operations

## Supported installation

The application uses official **DSH 0.2.1-rc.2**, Node.js **24.19.0**, and pnpm
**11.28.5**. `runtime/pnpm-lock.yaml` locks the full host dependency graph.
Python **3.10+**, `venv`, `curl`, and a working Internet connection are required.
The server launcher supports Linux and macOS. On Windows use WSL for the server,
or connect to a deployed server using the desktop client.

From an extracted source release:

```bash
./maple
```

The first launch installs the runtime and plugin under
`~/.local/share/maple-harness`. Later launches reuse that installation. A changed
release manifest or DSH lockfile triggers installation of the new snapshot.
`./scripts/bootstrap_local.sh` explicitly reinstalls a development checkout.
No administrator access is needed for a local launch.

Open the launch link printed by DSH. The default address uses port **3000**.
The link pairs the browser with this installation using official DSH browser
authentication. No username or password is needed. Do not publish the link or
paste its token into an issue. Enter the DeepSeek API key in **MAPLE Settings**.
The host and all optimization agent roles use **`deepseek-flash`**, never Pro.
Evolutionary search defaults to **100** iterations and remains configurable.

## Installation and state isolation

This repository includes a core snapshot in `vendor/liveopt-core/`.
`LIVEOPT_CORE_ROOT` can select a different, explicit core checkout. The installer
builds from temporary copies, keeping setuptools products out of source trees.
It does not modify the paper, benchmark runners, reference fronts, or their caches.

Each installation contains:

```text
MAPLE_HOME/
  bin/                  launcher wrappers
  runtime/venv/         installed Python core and sidecar
  runtime/dsh-bundle/   installed application plugin
  dsh-runtime/          locked official DSH runtime
  dsh-home/             official profiles and credentials
  workspace/            default public-data workspace
  state/                accepted sessions, uploads, artifacts, and caches
```

Choose a separate installation or port without changing the existing service:

```bash
MAPLE_HOME=/path/to/maple-next MAPLE_PORT=3002 ./maple
```

The previous `~/.local/share/liveopt-dsh` deployment is not overwritten, and old
DSH profiles are not migrated automatically. Back up application state and DSH
home before testing a copy of existing sessions on a new host version. Do not
run two sidecars against the same writable state directory.

`LIVEOPT_MCP_WORKSPACE_ROOT` selects the public input directory.
`LIVEOPT_MCP_STATE_DIR` selects a separate writable state directory. The launcher
sets both explicitly. Provider caches and traces use only application-scoped
locations, not inherited experiment paths. `LIVEOPT_MCP_CACHE_MODE` supports
`read_write`, `cache_only`, and `off`.

## Network access and credentials

Use `LIVEOPT_MCP_NETWORK_MODE=auto` to honor a configured proxy, `direct` to
connect directly from the sidecar, or `system_proxy` to require that proxy.
The official host uses standard proxy variables through `NODE_USE_ENV_PROXY=1`.
Background services must have their own reachable proxy, not a proxy available
only while a VS Code tunnel is open.

An optional `LIVEOPT_ENV_FILE=/private/path/provider.env` supplies launch settings.
A launch-time `DEEPSEEK_API_KEY` is moved into the DSH credential store before
starting the application processes. The versioned `.credentials.yaml` contains
`version: 1` and a `refs` map, with owner-only permissions. Saving an API key
preserves unrelated credential records. Keys are not MCP arguments and are not
written into session snapshots or exported plans.

The browser accesses uploads, settings, progress, and downloads through the
same-origin `/liveopt-api` route. The plugin applies official DSH connection and
origin checks before forwarding to a loopback-only sidecar. It does not expose a
second browser-facing port or bypass authentication in the reverse proxy.

## Intranet and background deployment

Keep DSH on loopback and use the provided HTTPS reverse proxy on a private IPv4
address. The intranet bootstrap currently supports Linux x64:

```bash
./scripts/bootstrap_local.sh
./scripts/bootstrap_intranet.sh
./scripts/start_intranet.sh
```

The default private port is **3000**, with DSH on **127.0.0.1:3001**. A second
installation must use different ports. Set `LIVEOPT_INTRANET_BIND` explicitly if
automatic address detection is unsuitable. The launch link is stored in the
installation's `logs/dsh-intranet.log`. Caddy uses a private CA under
`MAPLE_HOME/caddy-data/caddy/pki/authorities/local/root.crt`; verify and import it
on trusted clients. Do not disable certificate validation globally.

Install a user service after the interactive deployment has passed testing:

```bash
./scripts/install_systemd_user.sh
sudo loginctl enable-linger "$USER"
systemctl --user status maple-intranet.service
journalctl --user -u maple-intranet.service -f
```

This uses a new **maple-intranet.service**, leaving an existing
`liveopt-intranet.service` unchanged. Proxy configuration is saved in
`~/.config/maple-harness/service.env`. Override the config root with
`LIVEOPT_CONFIG_ROOT` during installation.

Generated Workbench slots execute Python with the server user's permissions.
Deploy only to trusted users or use an isolation boundary suited to your threat
model. A token protects access but does not sandbox generated code. Container
metadata is included for standalone builds; local and intranet installation are
the primary validated paths for this upgrade.

## Data, solving, and results

Three application skills cover data preparation, solving/updates, and export.
The MCP server registers the following tools through DSH's official MCP client:

| Tool | Action |
|---|---|
| `liveopt_prepare_data` | Prepare inline records or workspace CSV/TSV/JSON/JSONL/XLSX inputs. |
| `liveopt_prepare_uploads` | Read browser uploads, including tables and TXT/Markdown/PDF/DOCX documents. |
| `liveopt_map_data` | Use the LLM to map native-language schema labels while retaining original names. |
| `liveopt_start` | Build a TSS Workbench and solve with `auto`, `exact`, or `evolutionary` routing. |
| `liveopt_update` | Revise an accepted session through a natural-language request. |
| `liveopt_override_slots` | Validate user-provided Workbench slots after an unsuccessful automatic repair. |
| `liveopt_wait` | Wait silently while the browser progress card refreshes independently. |
| `liveopt_inspect` | Read status, accepted state, code slots, or per-turn records. |
| `liveopt_export` | Export solutions, population, iterations, JSON, CSV, and ZIP artifacts. |
| `liveopt_cancel` | Cancel queued work without interrupting an atomic transition. |

Uploads are checksum-verified and stored outside the checkout. The default
per-file limit is **25 MiB**, configurable with `LIVEOPT_MCP_MAX_UPLOAD_BYTES`.
Prose extraction is bounded by `LIVEOPT_MCP_MAX_DOCUMENT_CHARS` and reports
truncation. Documents are public problem context, not executable instructions.

The data mapper preserves cell values, units, and entity identifiers. It retains
reversible field aliases for localized results. Mutable resources are represented
as public rows so ordinary membership changes can use structured data patches.
When code must change, the application requests JSON slot strings, accepts older
fenced output through its compatibility parser, and reports syntax locations to
bounded repair. Manual slot overrides can continue the same accepted session.

`start` and `update` return job IDs. A single `wait` call keeps the model silent
while progress displays generations, feasibility, and archive size. Updates show
the restart action and reused-candidate count once seeds are built. Exact solves
display their solver phase and elapsed time. The exact solver's default time
limit is **30 seconds**; any accepted incumbent must pass numerical validation.

The **Solutions** view follows the selected conversation. Each accepted turn has
its request, restart action, objective trajectories, final population, Pareto
set, code slots, data changes, and downloads. The separate solution explorer
highlights a selected feasible plan and saves the preference. It does not change
the accepted optimizer state merely because a plan is selected for viewing.

## Persistence and recovery

```text
state/sessions/<id>/snapshot.json    current accepted state
state/sessions/<id>/events/         per-turn records
state/sessions/<id>/exports/        downloadable results
state/jobs/                        durable job status
state/cache/                       application-only response caches
state/provider_traces/             request metadata
state/application_settings.json    non-secret UI defaults
```

Accepted transitions are written atomically. On restart the sidecar rebuilds the
Workbench and population from the saved state. An interrupted job is not silently
treated as complete. Reusing its session/update ID allows cached provider calls
to be reused; completed updates are idempotent. Back up the whole state directory
rather than copying only the best solution.

## Offline verification

```bash
python -m pip install -e vendor/liveopt-core -e . pytest
python -m pytest -q
node --test tests/*.test.mjs tests/*.test.cjs desktop/tests/*.test.cjs
python scripts/smoke_web.py
PATH="$HOME/.local/share/maple-harness/bin:$PATH" ./scripts/smoke_dsh.sh
```

The web check boots a temporary profile and verifies pairing, origin checks,
settings, Chinese CSV upload, and installed explorer assets. The MCP check uses
a local Messages/Chat-Completions mock, not a paid provider. Both shut down their
test processes. Language tests can also load the installed official DSH modules
by setting `DSH_NODE_MODULES` to its module-resolution directory.
