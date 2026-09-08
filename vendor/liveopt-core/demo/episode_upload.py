"""Episode inputs for the demo: builtin NLDO episodes, uploads, or freeform text.

All three modes produce the same pair ``(problem_text, public_context)`` with
``public_context["tables"]`` materialized as lists of row dicts, matching the
runtime contract consumed by the Workbench generator and the dynamic runner.
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from evo2.benchmarks.optimization_contracts import public_optimization_contract_for_episode

REPO_ROOT = Path(__file__).resolve().parents[1]
NLDO_JSONL = REPO_ROOT / "data" / "evo2_dynoptbench" / "public_csv" / "nldo_15episodes_12updates_csv.jsonl"


@dataclass
class EpisodeInput:
    """Materialized episode ready for ``DemoSession.create``."""

    episode_id: str
    problem: str
    public_context: dict[str, Any]
    update_stream: list[dict[str, Any]] = field(default_factory=list)


def list_builtin_episode_ids() -> list[dict[str, str]]:
    episodes = []
    if not NLDO_JSONL.exists():
        return episodes
    with NLDO_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            episodes.append(
                {
                    "episode_id": str(row.get("episode_id")),
                    "domain": str(row.get("domain") or ""),
                    "family": str(row.get("family") or ""),
                    "update_count": len(row.get("update_stream") or []),
                }
            )
    return episodes


def load_builtin_episode(episode_id: str) -> EpisodeInput:
    """Load one builtin NLDO episode, resolving CSV paths against the repo root."""

    for entry in list_builtin_episode_ids():
        if entry["episode_id"] == episode_id:
            break
    else:
        raise ValueError(f"unknown builtin episode: {episode_id}")
    with NLDO_JSONL.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            if str(row.get("episode_id")) == episode_id:
                return _episode_input_from_payload(row, base_dir=REPO_ROOT)
    raise ValueError(f"unknown builtin episode: {episode_id}")


def load_uploaded_episode(
    payload: dict[str, Any],
    csv_files: dict[str, str],
    work_dir: Path,
) -> EpisodeInput:
    """Materialize an uploaded episode JSON plus its CSV files.

    ``csv_files`` maps file names to CSV text. Files are written under the
    per-session ``work_dir`` and every ``csv_tables`` path that matches an
    uploaded file name is rewritten to point at the local copy.
    """

    if not isinstance(payload, dict):
        raise ValueError("uploaded episode must be a JSON object (one jsonl line)")
    work_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, text in csv_files.items():
        safe_name = Path(str(name)).name
        if not safe_name:
            continue
        target = work_dir / safe_name
        target.write_text(text, encoding="utf-8")
        written[safe_name] = target
    payload = json.loads(json.dumps(payload))  # deep copy of JSON data
    public_context = payload.get("public_context")
    if not isinstance(public_context, dict):
        raise ValueError("uploaded episode is missing public_context")
    csv_tables = public_context.get("csv_tables") or {}
    for name, meta in csv_tables.items():
        if not isinstance(meta, dict):
            continue
        basename = Path(str(meta.get("path") or "")).name
        if basename in written:
            meta["path"] = str(written[basename])
    return _episode_input_from_payload(payload, base_dir=REPO_ROOT)


def freeform_episode(problem: str, tables: dict[str, Any]) -> EpisodeInput:
    """Build an episode from raw problem text plus pasted tables.

    ``tables`` maps a table name to either CSV text (with a header row) or an
    already-parsed list of row dicts.
    """

    problem = str(problem or "").strip()
    if not problem:
        raise ValueError("freeform episode requires problem text")
    parsed: dict[str, list[dict[str, Any]]] = {}
    for name, value in (tables or {}).items():
        if isinstance(value, str):
            parsed[str(name)] = read_csv_rows(io.StringIO(value))
        elif isinstance(value, list):
            parsed[str(name)] = [dict(row) if isinstance(row, dict) else {"value": row} for row in value]
        else:
            raise ValueError(f"table {name!r} must be CSV text or a list of rows")
    return EpisodeInput(
        episode_id="freeform",
        problem=problem,
        public_context={"tables": parsed},
    )


def _episode_input_from_payload(payload: dict[str, Any], *, base_dir: Path) -> EpisodeInput:
    episode_id = str(payload.get("episode_id") or "episode")
    problem = str(payload.get("public_initial_problem") or payload.get("initial_natural_language_task") or "")
    if not problem.strip():
        raise ValueError("episode is missing public_initial_problem")
    public_context = public_context_with_loaded_tables(payload, base_dir=base_dir)
    updates = []
    for index, update in enumerate(payload.get("update_stream") or [], start=1):
        if not isinstance(update, dict):
            continue
        updates.append(
            {
                "update_id": str(update.get("update_id") or f"u{index:03d}"),
                "text": str(update.get("natural_language_update") or update.get("public_update") or ""),
            }
        )
    return EpisodeInput(
        episode_id=episode_id,
        problem=problem,
        public_context=public_context,
        update_stream=updates,
    )


def public_context_with_loaded_tables(episode: dict[str, Any], *, base_dir: Path = REPO_ROOT) -> dict[str, Any]:
    """Load csv_tables path references into public_context['tables'].

    Mirrors the helper in ``scripts/llm_tests/run_liveopt_dynamic_nldo_benchmark_full.py``
    (copied, not imported, so the demo does not depend on the batch script).
    """

    public_context = dict(episode.get("public_context") or {})
    tables = {}
    for name, meta in (public_context.get("csv_tables") or {}).items():
        path = Path(meta["path"])
        if not path.is_absolute():
            path = base_dir / path
        tables[name] = read_csv_rows(path)
    public_context["tables"] = tables
    optimization_contract = public_optimization_contract_for_episode(episode)
    if optimization_contract:
        public_context["optimization_contract"] = optimization_contract
        public_context["objective_sense"] = optimization_contract.get("objective_sense")
        public_context["multi_objective"] = optimization_contract.get("objective_mode") == "multi_objective"
    return public_context


def read_csv_rows(source: Any) -> list[dict[str, Any]]:
    """Read CSV text/a path/a file object into coerced row dicts."""

    if isinstance(source, Path):
        with source.open(newline="", encoding="utf-8") as handle:
            return [{key: coerce_cell(value) for key, value in row.items()} for row in csv.DictReader(handle)]
    return [{key: coerce_cell(value) for key, value in row.items()} for row in csv.DictReader(source)]


def coerce_cell(value: Any) -> Any:
    text = str(value).strip()
    if text.lower() == "true":
        return True
    if text.lower() == "false":
        return False
    try:
        number = float(text)
    except (TypeError, ValueError):
        return text
    return int(number) if number.is_integer() else number
