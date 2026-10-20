<div align="center">

<img src="src/liveopt_dsh/assets/maple-logo.png" width="80" alt="MAPLE Harness logo">

# MAPLE Harness

**Describe a plan. Compare solutions. Update it in conversation.**

[Download v0.2.0](https://github.com/xin8coder/MAPLE-harness-core/releases/tag/v0.2.0) · [User guide](docs/user-guide.md) · [中文指南](docs/user-guide.zh-CN.md) · [Recorded demo](https://xin8coder.github.io/MAPLE-harness/)

![Windows and Linux](https://img.shields.io/badge/Platforms-Windows%20%7C%20Linux-087e8b)
![DSH](https://img.shields.io/badge/DSH-0.2.1--rc.2-334B60)
![License ISC](https://img.shields.io/badge/License-ISC-39857D)

English | [简体中文](README.zh-CN.md)

</div>

MAPLE Harness turns natural-language requirements and uploaded data into numerical
optimization tasks. Compare single-objective or Pareto solutions, select a plan,
then revise the same task when orders, resources, deadlines, or objectives change.
Examples include production scheduling, warehouse allocation, staffing, delivery,
and other planning tasks.

The application uses the official DeepSeek Harness host and a separately installed
MAPLE optimization runtime. Code and examples retain some earlier `LiveOpt` names.

## Download and Start

Download a package from [Releases](https://github.com/xin8coder/MAPLE-harness-core/releases/latest) and **extract it completely** before starting.

| Platform | Recommended package | Start |
|---|---|---|
| Windows 10/11 x64 | `MAPLE-Harness-0.2.0-source.zip` | Double-click `start.cmd`. |
| Linux x64 | `MAPLE-Harness-0.2.0-source.tar.gz` | Run `bash start.sh` in the extracted folder. |

The same packages contain the **complete web application and backend**. Python
and Node.js are downloaded automatically into a private application directory.
No administrator privileges, Docker, WSL, or preinstalled Python/Node are required.
Linux needs `curl`, `tar`, CA certificates, and a glibc-based distribution such as
Ubuntu or Debian. Linux arm64 is supported by the launcher but is not in the
native CI matrix. macOS retains the manual installation path in the operations guide.

The first installation needs Internet access and can take several minutes.
Later launches reuse the installed dependencies. The browser opens a paired local
page automatically. Keep the terminal open while using the application and press
Ctrl+C to stop it. On a headless server, use the printed link through an SSH tunnel
or the documented intranet deployment.

## First Session

1. Open **Settings → MAPLE Harness** and enter your DeepSeek API key. Real model calls use your account and may incur charges. All application roles use `deepseek-flash`, not Pro.
2. Choose a workspace, start a conversation, and describe your objectives and hard constraints. Use **Document** to attach Excel, CSV, JSON, or supported documents.
3. Ask the agent to inspect the data first. Choose an exact or evolutionary solver when prompted. You can also ask it to select a route automatically.
4. Follow the progress card. In **Solutions**, inspect the objective curves, final population, and Pareto alternatives. Open the solution explorer to highlight and select a feasible plan.
5. Send an update in the **same conversation**. MAPLE retains the accepted task and search state, reports its restart action, and produces a new result.
6. Download the generated CSV, JSON, or ZIP files from the result view.

English and Simplified Chinese are supported. Chinese questions receive Chinese
replies without an extra language instruction. Chinese spreadsheet headers can be
mapped with LLM assistance; original labels are retained for localized results.

The default evolutionary budget is **100 iterations**, configurable in Settings.
There is no application username/password prompt. The launch link pairs your
browser with the local host, so keep its token private.

## Try the Included Example

The [Chinese garment-export example](examples/garment_export/inputs/chinese/)
includes an Excel workbook and ready-to-use requests. It covers orders, team
assignments, work sequence, warehouse zones, costs, and late deliveries.

> We have six export orders to pack tomorrow. Please assign teams, decide the
> order of work, and choose warehouse zones. I want lower costs and fewer late
> deliveries. Show several alternatives, and follow the rules in the workbook.
> Inspect the data first and do not start solving yet.

After accepting a solve, continue with a deadline or staffing change. See the
[English guide](docs/user-guide.md) or [中文操作指南](docs/user-guide.zh-CN.md) for
the exact included requests and how to compare accepted turns.

## Web App or Desktop Client?

**Use the source ZIP/tar.gz for one-click local web deployment.** It installs the
backend and opens the browser. The optional [`desktop/`](desktop/) package is an
Electron **remote client** for an already running MAPLE server. It does not bundle
the optimizer, Python, or a local backend. Native client packages, when attached to
a release, are labeled separately from the recommended web deployment packages.

## Settings, Storage, and Updates

The preferred local port is **3000**. If it is occupied, the native launcher
selects a free port. Advanced options:

```bash
# Linux: install without starting, or start without opening a browser.
bash start.sh --install-only
bash start.sh --no-browser

# Optional isolated installation and preferred port.
MAPLE_HOME=/path/to/maple MAPLE_PORT=3002 bash start.sh
```

On Windows use `start.cmd -InstallOnly` or `start.cmd -NoBrowser`.

State lives under `~/.local/share/maple-harness` on Linux or
`%LOCALAPPDATA%\MAPLEHarness` on Windows, not in the extracted source folder.
Back up this directory before upgrading. Stop the old launcher, extract the new
release, and start it under the same application home. The installer refreshes
the runtime when the release manifest changes. Older `liveopt-dsh` installations
are not imported automatically.

For shared access, network/proxy configuration, persistent services, recovery,
and security boundaries, read the [operations guide](docs/operations.md).
Generated Workbench code runs with the server user's permissions. Use trusted
data and users, or provide appropriate isolation before exposing the application.

## Validation and Development

The native [Windows/Linux workflow](.github/workflows/source.yml) installs the
application from scratch, runs the Python suite, checks authenticated web routes
and Chinese CSV uploads, and exercises the real DSH-to-MCP boundary with a local
provider mock. Tests do not spend model API credits. The vendored core and source
files are recorded in `RELEASE_MANIFEST.json`; release archives include checksums.

```bash
python -m pip install -e vendor/liveopt-core -e . pytest
python -m pytest -q
node --test tests/*.test.mjs tests/*.test.cjs desktop/tests/*.test.cjs
python scripts/smoke_web.py
python scripts/smoke_mcp_host.py
```

The executable application is separate from the research experiment entrypoints
and caches. [Implementation notes](docs/dsh-upgrade.md) describe the DSH migration.

## License

MAPLE Harness is released under the [ISC License](LICENSE). DeepSeek Harness keeps
its upstream MIT license and attribution. Bundled third-party notices are retained.
