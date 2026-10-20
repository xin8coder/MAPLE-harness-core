"""Portable result bundles for accepted LiveOpt sessions."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from typing import Any

from .serialization import candidate_summary, evolution_from_record, json_safe
from .store import StateStore
from .localization import display_label, localize_value, _label


def export_session(store: StateStore, session_id: str, result_labels: dict[str, str] | None = None) -> dict[str, Any]:
    snapshot = store.load_snapshot(session_id)
    result = evolution_from_record(snapshot["result"])
    objective_names = list((snapshot.get("problem_spec") or {}).get("objective_names") or [])
    if not objective_names:
        candidates_for_width = [result.best, *result.archive, *result.population]
        objective_count = max(
            (
                len(candidate.result.objectives or [])
                for candidate in candidates_for_width
                if candidate.result is not None
            ),
            default=0,
        )
        objective_names = [f"objective {index + 1}" for index in range(objective_count)]
    candidates = _candidate_rows(result, objective_names)
    population = _population_rows(result, objective_names)
    history = _history_rows(store, snapshot, objective_names)
    turn = int(snapshot.get("turn") or 0)
    localization = (snapshot.get("public_context") or {}).get("localization") or {}
    export_root = f"exports/t{turn:03d}"
    field_paths = set(objective_names)

    def collect_fields(value, prefix=""):
        if isinstance(value, list):
            for item in value:
                collect_fields(item, prefix)
        elif isinstance(value, dict):
            for key, item in value.items():
                path = f"{prefix}.{key}" if prefix else key
                field_paths.add(path)
                collect_fields(item, path)

    for candidate in [result.best, *result.archive, *result.population]:
        collect_fields((candidate_summary(candidate) or {}).get("solution") or {})
    try:
        saved_labels = json.loads(store.resolve_artifact(f"sessions/{session_id}/{export_root}/display_labels.json").read_text())
    except FileNotFoundError:
        saved_labels = {}
    for path, label in (result_labels or {}).items():
        if path not in field_paths:
            raise ValueError(f"unknown result field or objective: {path}")
        original_label = (localization.get("labels") or {}).get(path)
        if original_label and original_label != label:
            raise ValueError(f"result label conflicts with original source label: {path}")
        saved_labels[path] = _label(label)
    if localization:
        localization["labels"] = {**localization.get("labels", {}), **saved_labels}
    elif saved_labels:
        raise ValueError("prepare a language mapping before attaching result labels")
    if result_labels:
        store.save_session_bytes(session_id, f"{export_root}/display_labels.json", json.dumps(saved_labels, ensure_ascii=False).encode())
    unmapped = [path for path in sorted(field_paths) if path not in (localization.get("labels") or {})
                and path.rsplit(".", 1)[-1] not in (localization.get("labels") or {})
                and path.rsplit(".", 1)[-1].isascii()]

    solutions_csv = _csv_bytes(candidates)
    population_csv = _csv_bytes(population)
    history_csv = _csv_bytes(history)
    bundle = {
        "schema_version": 1,
        "session": {
            "session_id": session_id,
            "task_id": snapshot.get("task_id"),
            "turn": turn,
            "solver_preference": snapshot.get("solver_preference", "auto"),
            "objective_names": objective_names,
        },
        "best": candidate_summary(result.best),
        "solution_set": [candidate_summary(item) for item in result.archive],
        "final_population": [candidate_summary(item) for item in result.population],
        "iteration_history": history,
        "localization": localization,
        "unmapped_result_fields": unmapped if localization else [],
    }
    bundle_json = json.dumps(json_safe(bundle), ensure_ascii=False, indent=2).encode("utf-8")
    files = {
        "solutions.csv": solutions_csv,
        "final_population.csv": population_csv,
        "iteration_history.csv": history_csv,
        "result_bundle.json": bundle_json,
    }
    if localization:
        translated_names = [display_label(name, localization) for name in objective_names]
        localized_rows = []
        chinese = localization.get("language") == "zh"
        for index, row in enumerate(candidates):
            translated = {
                "方案序号" if chinese else "Plan": index + 1,
                "可行" if chinese else "Feasible": row["feasible"],
                "帕累托方案" if chinese else "Pareto": row["is_pareto"],
            }
            values = [value for key, value in row.items() if key.startswith("objective_")]
            for i, value in enumerate(values):
                name = translated_names[i] if i < len(translated_names) else f"Objective {i + 1}"
                translated[f"{i + 1}. {name}"] = value
            translated["方案明细" if chinese else "Details"] = json.dumps(
                localize_value(json.loads(row["solution_json"]), localization), ensure_ascii=False)
            localized_rows.append(translated)
        files["solutions_localized.csv"] = _csv_bytes(localized_rows)
        files["solutions_localized.json"] = json.dumps(localized_rows, ensure_ascii=False, indent=2).encode()
        files["field_mapping.json"] = json.dumps(localization, ensure_ascii=False, indent=2).encode()
    for name, content in files.items():
        store.save_session_bytes(session_id, f"{export_root}/{name}", content)

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in files.items():
            archive.writestr(name, content)
    store.save_session_bytes(
        session_id, f"{export_root}/liveopt_results.zip", zip_buffer.getvalue()
    )

    names = [*files, "liveopt_results.zip"]
    downloads = [
        {
            "name": name,
            "url": f"/liveopt-api/artifacts/sessions/{session_id}/{export_root}/{name}",
        }
        for name in names
    ]
    objective_keys = [
        key
        for row in candidates
        for key in row
        if key.startswith("objective_")
    ]
    preview_keys = ["solution_index", "source", "feasible", "scalar"] + list(
        dict.fromkeys(objective_keys)
    )
    response = {
        "session_id": session_id,
        "turn": turn,
        "objective_names": [display_label(name, localization) for name in objective_names],
        "localization": localization,
        "unmapped_result_fields": unmapped if localization else [],
        "solution_count": len(result.archive),
        "population_count": len(result.population),
        "downloads": downloads,
        "solution_preview": [
            {key: row.get(key) for key in preview_keys} for row in candidates[:12]
        ],
        "population_preview": [_plot_point(row, objective_names) for row in population[:1000]],
        "pareto_preview": [
            _plot_point(row, objective_names)
            for row in candidates
            if row.get("is_pareto")
        ][:500],
        "objective_series": _objective_series(history, objective_names, turn),
        "history_preview": history[-240:],
    }
    for series in response["objective_series"]:
        series["name"] = display_label(series["name"], localization)
    store.save_session_bytes(
        session_id,
        f"{export_root}/ui_result.json",
        json.dumps(json_safe(response), ensure_ascii=False).encode("utf-8"),
    )
    return response


def _candidate_rows(result: Any, objective_names: list[str]) -> list[dict[str, Any]]:
    candidates = [("best", result.best)] + [
        ("archive", candidate) for candidate in result.archive
    ]
    pareto_genomes = {
        json.dumps(
            (candidate_summary(candidate) or {}).get("genome"),
            sort_keys=True,
            ensure_ascii=False,
        )
        for candidate in result.archive
    }
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source, candidate in candidates:
        summary = candidate_summary(candidate) or {}
        identity = json.dumps(summary.get("genome"), sort_keys=True, ensure_ascii=False)
        if identity in seen:
            continue
        seen.add(identity)
        row: dict[str, Any] = {
            "solution_index": len(rows),
            "source": source,
            "is_pareto": identity in pareto_genomes,
            "feasible": summary.get("feasible"),
            "scalar": summary.get("scalar"),
        }
        objectives = list(summary.get("objectives") or [])
        for index, value in enumerate(objectives):
            raw_name = objective_names[index] if index < len(objective_names) else "objective"
            row[f"objective_{_column_name(raw_name, index)}"] = value
        row["solution_json"] = json.dumps(
            summary.get("solution") or {}, ensure_ascii=False, sort_keys=True
        )
        row["genome_json"] = json.dumps(
            summary.get("genome") or {}, ensure_ascii=False, sort_keys=True
        )
        row["violations_json"] = json.dumps(
            summary.get("violations") or {}, ensure_ascii=False, sort_keys=True
        )
        rows.append(row)
    return rows


def _population_rows(result: Any, objective_names: list[str]) -> list[dict[str, Any]]:
    pareto_genomes = {
        json.dumps(
            (candidate_summary(candidate) or {}).get("genome"),
            sort_keys=True,
            ensure_ascii=False,
        )
        for candidate in result.archive
    }
    rows: list[dict[str, Any]] = []
    for index, candidate in enumerate(result.population):
        summary = candidate_summary(candidate) or {}
        identity = json.dumps(summary.get("genome"), sort_keys=True, ensure_ascii=False)
        row: dict[str, Any] = {
            "solution_index": index,
            "source": "population",
            "is_pareto": identity in pareto_genomes,
            "rank": int(getattr(candidate, "rank", 10**9)),
            "feasible": summary.get("feasible"),
            "scalar": summary.get("scalar"),
        }
        objectives = list(summary.get("objectives") or [])
        for objective_index, value in enumerate(objectives):
            raw_name = (
                objective_names[objective_index]
                if objective_index < len(objective_names)
                else "objective"
            )
            row[f"objective_{_column_name(raw_name, objective_index)}"] = value
        row["solution_json"] = json.dumps(
            summary.get("solution") or {}, ensure_ascii=False, sort_keys=True
        )
        row["genome_json"] = json.dumps(
            summary.get("genome") or {}, ensure_ascii=False, sort_keys=True
        )
        rows.append(row)
    return rows


def _history_rows(
    store: StateStore,
    snapshot: dict[str, Any],
    objective_names: list[str],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    final_turn = int(snapshot.get("turn") or 0)
    for turn in range(final_turn + 1):
        try:
            event = store.load_event(snapshot["session_id"], turn)
        except KeyError:
            event = {}
        history = list(event.get("history") or [])
        if turn == final_turn and not history:
            history = list((snapshot.get("result") or {}).get("history") or [])
        update_id = event.get("update_id") or ("t000" if turn == 0 else f"t{turn:03d}")
        for item in history:
            if not isinstance(item, dict):
                continue
            known = {
                "turn": turn,
                "update_id": update_id,
                "generation": item.get("generation"),
                "population_size": item.get("population"),
                "feasible_count": item.get("feasible"),
                "archive_size": item.get("archive_count", item.get("front_size")),
                "front_size": item.get("front_size"),
                "best_scalar": item.get("best_scalar"),
            }
            for prefix in ("objective_min", "objective_mean", "objective_max"):
                values = list(item.get(prefix) or [])
                for index, value in enumerate(values):
                    name = objective_names[index] if index < len(objective_names) else "objective"
                    known[f"{prefix}_{_column_name(name, index)}"] = value
            extra = {
                key: value
                for key, value in item.items()
                if key
                not in {
                    "generation",
                    "population",
                    "feasible",
                    "archive_count",
                    "front_size",
                    "best_scalar",
                    "candidate_archive",
                    "objective_min",
                    "objective_mean",
                    "objective_max",
                }
            }
            known["metrics_json"] = json.dumps(json_safe(extra), sort_keys=True)
            rows.append(known)
    return rows


def _plot_point(row: dict[str, Any], objective_names: list[str]) -> dict[str, Any]:
    objective_keys = [
        key for key in row if key.startswith("objective_")
    ]
    return {
        "solution_index": row.get("solution_index"),
        "feasible": row.get("feasible"),
        "is_pareto": row.get("is_pareto", False),
        "objectives": [row.get(key) for key in objective_keys],
        "objective_names": objective_names[: len(objective_keys)],
    }


def _objective_series(
    history: list[dict[str, Any]], objective_names: list[str], turn: int
) -> list[dict[str, Any]]:
    selected = [row for row in history if int(row.get("turn") or 0) == int(turn)]
    series: list[dict[str, Any]] = []
    for index, raw_name in enumerate(objective_names or ["objective"]):
        suffix = _column_name(raw_name, index)
        minimum_key = f"objective_min_{suffix}"
        mean_key = f"objective_mean_{suffix}"
        maximum_key = f"objective_max_{suffix}"
        points = [
            {
                "generation": row.get("generation"),
                "minimum": row.get(minimum_key),
                "mean": row.get(mean_key),
                "maximum": row.get(maximum_key),
            }
            for row in selected
            if row.get(minimum_key) is not None
        ]
        if points:
            series.append({"name": raw_name, "points": points})
    return series


def _csv_bytes(rows: list[dict[str, Any]]) -> bytes:
    output = io.StringIO(newline="")
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    if fields:
        writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def _column_name(value: str, index: int) -> str:
    cleaned = "".join(character if character.isalnum() else "_" for character in str(value))
    return cleaned.strip("_").lower() or str(index + 1)
