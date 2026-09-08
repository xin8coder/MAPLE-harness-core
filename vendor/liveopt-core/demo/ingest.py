"""Data ingestion for the demo: arbitrary user data -> NLDO-style episode.

Users drop files or paste tables plus a goal description; an LLM conversion
tool turns the parsed tables into the episode format the real LiveOpt
pipeline consumes (``episode_id``, ``public_initial_problem``,
``public_context.tables`` plus a minimal public optimization contract).
Parsing is stdlib-only (csv/tsv/json/markdown/whitespace tables); .xlsx is
supported only when openpyxl happens to be installed.
"""

from __future__ import annotations

import csv
import importlib.util
import io
import json
from pathlib import Path
from typing import Any

from demo.episode_upload import EpisodeInput, coerce_cell

CONVERT_SYSTEM = """You convert user-provided data into a structured optimization episode for the LiveOpt Workbench.

Given table summaries (name, columns, sample rows) and the user's goal, return exactly one JSON object:
{
  "episode_id": "short snake_case id",
  "public_initial_problem": "complete natural-language problem statement. Name every table and column the solver must read, state all constraints, and append a 'Scoring rules:' section describing exactly how the plan is scored.",
  "objective": {
    "objective_mode": "single_objective" or "multi_objective",
    "objective_sense": "minimize" or "maximize",
    "objective_names": ["<one name per objective>"],
    "hard_constraints": ["<one sentence per constraint>"],
    "objective_terms": [{"name": "<term>", "formula": "<how it is computed from the tables>", "source": "<table/columns>"}],
    "scalar_formula": "<how terms combine into the scalar>",
    "solution_output_format": "<JSON shape of the plan, using scalar public ids>"
  }
}

Rules:
- Do NOT return any table data. The system keeps the full parsed tables verbatim; you only see samples to understand their shape. Any "tables" field in your response is ignored.
- Refer to rows only through their existing id columns; do not invent entities or values.
- Do not invent data; if the goal is ambiguous, make the most literal interpretation and say so in the problem statement.
- Return the JSON object only, no markdown fences."""

SCALAR_TYPES = (str, int, float, bool)


class IngestError(ValueError):
    """User-facing ingestion failure (bad file, unsupported format, invalid conversion)."""


# ---------------------------------------------------------------- parsers


def parse_table_text(text: str, *, name: str = "table") -> dict[str, list[dict[str, Any]]]:
    """Parse pasted text as CSV/TSV/JSON/markdown/whitespace table(s)."""

    text = str(text or "").strip()
    if not text:
        raise IngestError("empty table text")
    if text[0] in "[{":
        return parse_json_tables(text)
    if "|" in text.splitlines()[0]:
        return {name: parse_markdown_table(text)}
    sample = text[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",\t;")
        rows = _read_csv(io.StringIO(text), dialect.delimiter)
        if len(rows[0]) > 1:
            return {name: rows}
    except (csv.Error, IndexError):
        pass
    return {name: parse_whitespace_table(text)}


def parse_json_tables(text: str) -> dict[str, list[dict[str, Any]]]:
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise IngestError(f"invalid JSON: {exc}") from exc
    if isinstance(payload, list):
        return {"data": _rows_from_list(payload)}
    if isinstance(payload, dict):
        # One table given as column -> list of scalars.
        if payload and all(isinstance(value, list) and not any(isinstance(item, dict) for item in value) for value in payload.values()):
            keys = list(payload)
            length = max(len(payload[key]) for key in keys)
            rows = [{key: (payload[key][index] if index < len(payload[key]) else None) for key in keys} for index in range(length)]
            return {"data": rows}
        return {str(name): _rows_from_list(value) for name, value in payload.items()}
    raise IngestError("JSON data must be a list of rows or an object of tables")


def _rows_from_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise IngestError("table must be a list of rows")
    rows = []
    for item in value:
        if isinstance(item, dict):
            rows.append(dict(item))
        else:
            rows.append({"value": item})
    return rows


def parse_markdown_table(text: str) -> list[dict[str, Any]]:
    lines = [line.strip().strip("|") for line in text.splitlines() if line.strip()]
    if not lines:
        raise IngestError("empty markdown table")
    header = [cell.strip() for cell in lines[0].split("|")]
    rows = []
    for line in lines[1:]:
        cells = [cell.strip() for cell in line.split("|")]
        if all(set(cell) <= set("-: ") for cell in cells):  # separator row
            continue
        if len(cells) < len(header):
            cells += [""] * (len(header) - len(cells))
        rows.append({header[index]: coerce_cell(cells[index]) for index in range(len(header))})
    if not rows:
        raise IngestError("markdown table has no data rows")
    return rows


def parse_whitespace_table(text: str) -> list[dict[str, Any]]:
    import re

    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        raise IngestError("empty table text")
    header = [cell.strip() for cell in re.split(r"\s{2,}|\t", lines[0].strip()) if cell.strip()]
    if len(header) < 2:
        raise IngestError("could not detect a table: use CSV, markdown, JSON, or aligned columns")
    rows = []
    for line in lines[1:]:
        cells = [cell.strip() for cell in re.split(r"\s{2,}|\t", line.strip())]
        if len(cells) != len(header):
            raise IngestError(f"row has {len(cells)} columns, expected {len(header)}: {line.strip()[:60]!r}")
        rows.append({header[index]: coerce_cell(cells[index]) for index in range(len(header))})
    return rows


def _read_csv(source: Any, delimiter: str) -> list[dict[str, Any]]:
    reader = csv.DictReader(source, delimiter=delimiter)
    return [{key: coerce_cell(value) for key, value in row.items()} for row in reader]


def parse_uploaded_file(name: str, content: str | bytes) -> dict[str, list[dict[str, Any]]]:
    """Parse one uploaded file by extension into named tables."""

    suffix = Path(name).suffix.lower()
    stem = Path(name).stem or "table"
    if suffix == ".xlsx":
        return _parse_xlsx(stem, content)
    text = content.decode("utf-8") if isinstance(content, bytes) else str(content)
    if suffix == ".tsv":
        return {stem: _read_csv(io.StringIO(text), "\t")}
    if suffix == ".csv":
        return {stem: _read_csv(io.StringIO(text), ",")}
    if suffix == ".json":
        return parse_json_tables(text)
    if suffix in {".md", ".txt", ""}:
        return parse_table_text(text, name=stem)
    # Unknown extension: try the generic text parser before giving up.
    try:
        return parse_table_text(text, name=stem)
    except IngestError as exc:
        raise IngestError(f"unsupported file type {suffix!r} for {name!r}: {exc}") from exc


def _parse_xlsx(stem: str, content: str | bytes) -> dict[str, list[dict[str, Any]]]:
    if importlib.util.find_spec("openpyxl") is None:
        raise IngestError(
            ".xlsx support requires the optional 'openpyxl' package; "
            "export the sheet as CSV and upload that instead"
        )
    import openpyxl  # noqa: PLC0415 - optional dependency, guarded above

    raw = content if isinstance(content, bytes) else content.encode("latin1")
    workbook = openpyxl.load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    tables: dict[str, list[dict[str, Any]]] = {}
    for sheet in workbook.worksheets:
        rows = [list(row) for row in sheet.iter_rows(values_only=True)]
        if not rows:
            continue
        header = [str(cell).strip() if cell is not None else f"col{index}" for index, cell in enumerate(rows[0])]
        table_name = f"{stem}_{sheet.title}" if len(workbook.worksheets) > 1 else stem
        tables[table_name] = [
            {header[index]: (row[index] if index < len(row) else None) for index in range(len(header))}
            for row in rows[1:]
            if any(cell is not None for cell in row)
        ]
    if not tables:
        raise IngestError("xlsx workbook contains no data rows")
    return tables


# ------------------------------------------------------------- validation


def validate_tables(tables: Any) -> dict[str, list[dict[str, Any]]]:
    if not isinstance(tables, dict) or not tables:
        raise IngestError("episode requires at least one named table")
    validated: dict[str, list[dict[str, Any]]] = {}
    for name, rows in tables.items():
        if not isinstance(rows, list) or not rows:
            raise IngestError(f"table {name!r} must be a non-empty list of row objects")
        checked = []
        for index, row in enumerate(rows):
            if not isinstance(row, dict):
                raise IngestError(f"table {name!r} row {index} is not an object")
            for key, value in row.items():
                if value is not None and not isinstance(value, SCALAR_TYPES):
                    raise IngestError(f"table {name!r} row {index} field {key!r} must be a scalar, got {type(value).__name__}")
            checked.append(dict(row))
        validated[str(name)] = checked
    return validated


def validate_objective(objective: Any) -> dict[str, Any]:
    if not isinstance(objective, dict):
        raise IngestError("conversion must declare an objective")
    names = [str(item) for item in objective.get("objective_names") or [] if str(item).strip()]
    if not names:
        raise IngestError("conversion must declare at least one objective name")
    mode = str(objective.get("objective_mode") or "single_objective").strip()
    if mode not in {"single_objective", "multi_objective"}:
        mode = "multi_objective" if len(names) > 1 else "single_objective"
    sense = str(objective.get("objective_sense") or "minimize").strip().lower()
    if sense not in {"minimize", "maximize"}:
        sense = "minimize"
    terms = []
    for term in objective.get("objective_terms") or []:
        if isinstance(term, dict) and str(term.get("name") or "").strip():
            terms.append(
                {
                    "name": str(term["name"]).strip(),
                    "kind": "objective",
                    "weight": 1.0,
                    "formula": str(term.get("formula") or ""),
                    "source": str(term.get("source") or ""),
                }
            )
    return {
        "objective_mode": mode,
        "objective_sense": sense,
        "objective_names": names,
        "hard_constraints": [str(item) for item in objective.get("hard_constraints") or [] if str(item).strip()],
        "objective_terms": terms,
        "scalar_formula": str(objective.get("scalar_formula") or ""),
        "solution_output_format": str(objective.get("solution_output_format") or ""),
    }


# ------------------------------------------------------- LLM conversion


def summarize_tables(tables: dict[str, list[dict[str, Any]]], *, sample_rows: int = 3) -> list[dict[str, Any]]:
    summary = []
    for name, rows in tables.items():
        columns = sorted({key for row in rows for key in row})
        summary.append(
            {
                "name": name,
                "columns": columns,
                "row_count": len(rows),
                "sample_rows": rows[:sample_rows],
            }
        )
    return summary


def convert_data_to_episode(
    client: Any,
    goal: str,
    tables: dict[str, list[dict[str, Any]]],
) -> EpisodeInput:
    """LLM conversion tool: parsed tables + goal text -> NLDO-style episode."""

    prompt = (
        "User goal:\n" + str(goal or "").strip() + "\n\n"
        "Parsed tables (name, columns, row count, sample rows):\n"
        + json.dumps(summarize_tables(tables), ensure_ascii=False, default=str)
    )
    response = client.chat(
        [
            {"role": "system", "content": CONVERT_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.0,
        max_tokens=4000,
    )
    content = ""
    if isinstance(response, dict):
        content = str(response.get("choices", [{}])[0].get("message", {}).get("content", "") or "")
    payload = _extract_json(content)
    return episode_from_conversion(payload, fallback_tables=tables)


def _extract_json(text: str) -> dict[str, Any]:
    stripped = str(text or "").strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`").strip()
        if stripped.startswith("json"):
            stripped = stripped[4:].strip()
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start < 0 or end <= start:
            raise IngestError("the conversion model did not return a JSON object") from None
        try:
            payload = json.loads(stripped[start : end + 1])
        except json.JSONDecodeError as exc:
            raise IngestError(f"the conversion model returned invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise IngestError("conversion response must be a JSON object")
    return payload


def episode_from_conversion(
    payload: dict[str, Any],
    *,
    fallback_tables: dict[str, list[dict[str, Any]]] | None = None,
) -> EpisodeInput:
    """Validate an LLM conversion payload and assemble the public_context.

    Parsed source tables always win over any tables the model may emit: the
    model only ever sees sampled rows, so its copy would silently drop data.
    """

    tables = validate_tables(fallback_tables or payload.get("tables") or {})
    objective = validate_objective(payload.get("objective"))
    problem = str(payload.get("public_initial_problem") or "").strip()
    if not problem:
        raise IngestError("conversion did not produce a problem statement")
    episode_id = str(payload.get("episode_id") or "imported").strip() or "imported"
    contract = {
        "version": "public_quantitative_objective_contract_v1",
        "benchmark_family": "user_imported",
        **objective,
        "solution_cardinality": "single_solution",
    }
    public_context = {
        "tables": tables,
        "csv_schema": {name: sorted({key for row in rows for key in row}) for name, rows in tables.items()},
        "optimization_contract": contract,
        "objective_sense": objective["objective_sense"],
        "multi_objective": objective["objective_mode"] == "multi_objective",
    }
    return EpisodeInput(
        episode_id=episode_id,
        problem=problem,
        public_context=public_context,
    )


def load_imported_episode(payload: dict[str, Any]) -> EpisodeInput:
    """Accept an already-converted episode (from a preview card confirmation)."""

    if not isinstance(payload, dict):
        raise IngestError("imported episode must be a JSON object")
    public_context = payload.get("public_context")
    if not isinstance(public_context, dict):
        raise IngestError("imported episode is missing public_context")
    tables = validate_tables(public_context.get("tables"))
    problem = str(payload.get("public_initial_problem") or "").strip()
    if not problem:
        raise IngestError("imported episode is missing public_initial_problem")
    context = dict(public_context)
    context["tables"] = tables
    return EpisodeInput(
        episode_id=str(payload.get("episode_id") or "imported"),
        problem=problem,
        public_context=context,
    )


def ingest_files_and_goal(
    client: Any,
    *,
    files: dict[str, str] | None = None,
    pasted_text: str = "",
    goal: str = "",
) -> EpisodeInput:
    """Full import pipeline: files + pasted tables + goal -> episode."""

    tables: dict[str, list[dict[str, Any]]] = {}
    for name, content in (files or {}).items():
        for table_name, rows in parse_uploaded_file(name, content).items():
            tables[table_name] = rows
    if str(pasted_text or "").strip():
        for table_name, rows in parse_table_text(pasted_text, name="pasted").items():
            tables[table_name] = rows
    if not tables:
        raise IngestError("no tabular data found: upload a file or paste a table")
    tables = validate_tables(tables)
    if not str(goal or "").strip():
        raise IngestError("describe the optimization goal so the data can be converted")
    return convert_data_to_episode(client, goal, tables)


def preview_card(episode: EpisodeInput) -> dict[str, Any]:
    """Card shown after conversion; the UI confirms to start optimization."""

    contract = episode.public_context.get("optimization_contract") or {}
    tables_summary = {
        name: {
            "columns": sorted({key for row in rows for key in row}),
            "rows": len(rows),
        }
        for name, rows in (episode.public_context.get("tables") or {}).items()
    }
    return {
        "type": "episode_preview",
        "title": "Imported episode preview",
        "data": {
            "episode_id": episode.episode_id,
            "problem": episode.problem,
            "tables": tables_summary,
            "objective": {
                "objective_mode": contract.get("objective_mode"),
                "objective_sense": contract.get("objective_sense"),
                "objective_names": contract.get("objective_names") or [],
                "scalar_formula": contract.get("scalar_formula") or "",
            },
            "episode_payload": {
                "episode_id": episode.episode_id,
                "public_initial_problem": episode.problem,
                "public_context": episode.public_context,
            },
        },
    }
