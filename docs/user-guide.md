# MAPLE Harness User Guide

[Download](https://github.com/xin8coder/MAPLE-harness-core/releases/latest) | [中文指南](user-guide.zh-CN.md) | [README](../README.md)

## 1. Start the Application

Download the source ZIP for Windows or source tar.gz for Linux and extract it
fully. Double-click `start.cmd` on Windows, or run `bash start.sh` on Linux.
You do not need Python, Node, Docker, or WSL installed beforehand. First launch
downloads dependencies; later launches reuse them.

The browser opens the application automatically. Keep the launcher terminal open.
If no browser opens, copy the complete launch link from the terminal into a
browser on the same machine. A headless remote host needs SSH forwarding or
[intranet deployment](operations.md#intranet-and-background-deployment).

Do not use a remote desktop-client package to install a local backend. The
recommended source packages include both the browser application and optimizer.

## 2. Configure the API Key

Open **Settings → MAPLE Harness**, save your DeepSeek API key, and set the default
iteration budget if needed. The default is **100**. All application roles use
`deepseek-flash`. Model calls are charged to your provider account; local numerical
search is separate. Downloads, package installation, and the recorded online demo
do not require a model key.

The browser pairs with the host through the launch link rather than an application
username/password. Keep its token and your API key private. The key is stored in
the host credential document, not in exported plans.

## 3. Provide the Problem and Data

Choose a workspace and start a conversation. State the desired outcome, the data
you have, and the constraints that must hold. Use **Document** to upload tables
or supported documents with the question. Do not paste a server-only file path.

Supported inputs include XLSX, CSV, TSV, JSON, JSONL, TXT, Markdown, PDF, and DOCX.
The default upload limit is **25 MiB per file**. Text extraction does not execute
spreadsheet macros or embedded code. If a document is truncated, inspect the
preparation result before continuing. Scanned images may need transcription.

You can ask the agent to inspect the data and clarify missing rules before
solving. English and Chinese requests are supported. An LLM-assisted mapping can
turn Chinese headers into internal aliases while retaining original labels,
identifiers, values, and units for outputs. Review clarification questions rather
than assuming an unstated business rule was inferred correctly.

## 4. Try the Included Production Example

Open [the Chinese input folder](../examples/garment_export/inputs/chinese/). Attach
`服装外贸排产数据.xlsx` and send `初始需求.txt`. It asks for assignments, work order,
and warehouse zones for six garment-export orders, considering cost and late
deliveries. It explicitly asks to inspect the data without starting a solve.

When ready, send `确认求解.txt`. This requests **60 candidates and at most 40
generations**, treating cost and lateness as separate objectives. These are
example-specific settings, not the application's default budget.

The example is synthetic business data, not a customer's production plan. Adapt
the workbook and check the generated formulation before operational use.

## 5. Choose How to Solve

For a supported linear/integer formulation, choose an exact solver. For complex
or Pareto tasks, choose evolutionary search. You can ask for automatic routing,
or specify a route and budget explicitly in the conversation. Evolutionary search
returns candidates; its search budget is not a guarantee of global optimality.

Multiple objectives remain separate when requested. Do not ask for a weighted
score unless combining those objectives is actually the intended preference.
Confirm costs, units, hard constraints, and any ambiguous priorities with the agent.

## 6. Inspect and Select a Plan

The progress card shows the numerical phase, generations, feasibility, and archive
size. The agent waits silently while this component refreshes. A 100-generation
request includes problem preparation/model time as well as numerical search.

After a successful solve, open **Solutions** in the same conversation. Inspect
the objective trajectories, final population, Pareto set, and exported results.
Use **Explore and select a plan** to open the separate explorer. Highlight a
feasible candidate to inspect its objectives and decision variables, then save
your preference. Selection records a preference; it does not by itself execute a
business plan or rewrite the optimizer's accepted state.

The solution view follows the conversation selected in the sidebar. Historical
turns retain their own request, data changes, search decisions, and result bundle.

## 7. Update the Same Task

Send `更新需求.txt` in the same conversation. The example advances a customer
deadline and reduces one team's headcount, leaving other rules unchanged. Do not
start a new session if the intent is to revise the existing plan.

MAPLE applies the update to the accepted task and checks whether previous
candidates can be reused. The progress component reports the selected restart
and reused-candidate count when available. Compare the accepted turns in
**Solutions**, including their requirements and objective values. If the update
fails, the last accepted state remains available; inspect the error or clarify
the request before retrying.

## 8. Download, Stop, and Return Later

Download generated CSV, JSON, and ZIP artifacts from the result view. Result
bundles can include solution sets, final populations, iteration history, and
reversible field mappings. Use the result's download link rather than **Open
Path**, which is a host-filesystem operation rather than a browser download.

Press Ctrl+C in the launcher terminal to stop. Start again from the same release
folder or a newer extracted version to reuse your application home. State is kept
in `~/.local/share/maple-harness` on Linux or `%LOCALAPPDATA%\MAPLEHarness` on Windows.
Back up that directory before upgrades. Do not delete it to fix an installation
problem, and do not run two backends against the same state concurrently.

## Troubleshooting

| Symptom | Action |
|---|---|
| First launch appears busy | Read the numbered terminal stages. Dependency downloads need Internet access; later launches reuse them. |
| Windows cannot find a script | Extract the entire ZIP before running `start.cmd`, not just the batch file. |
| Browser did not open | Use the full paired launch link printed in the terminal. Headless/SSH sessions do not have a local desktop browser. |
| API request fails | Check your key, provider balance, and Internet/proxy settings. Installation success does not imply a funded provider account. |
| An old bookmarked page returns 401/403 | Reopen the current launch link. Do not remove authentication or origin checks. |
| No new plan appears after a failed update | The previous accepted state is retained. Check the job error before submitting another update. |
| Download/Open Path fails | Use the result download link from the paired browser. Avoid a copied server-only path. |

See [operations](operations.md) for proxies, state recovery, private-network access,
and persistent deployment. This is a code-executing local application, not a
public multi-tenant hosted service.
