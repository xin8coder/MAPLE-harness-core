"""Read-only solution timeline views for the LiveOpt application UI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .serialization import json_safe
from .store import StateStore


def list_solution_sessions(store: StateStore) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for directory in store.sessions_dir.iterdir():
        if not directory.is_dir():
            continue
        try:
            snapshot = store.load_snapshot(directory.name)
        except (KeyError, OSError, ValueError):
            continue
        result = snapshot.get("result") or {}
        archive = result.get("archive") or []
        sessions.append(
            {
                "session_id": snapshot.get("session_id") or directory.name,
                "task_id": snapshot.get("task_id"),
                "turn": int(snapshot.get("turn") or 0),
                "title": _one_line(snapshot.get("initial_problem"), 120),
                "solver_preference": snapshot.get("solver_preference", "auto"),
                "objective_names": _objective_names(snapshot),
                "solution_count": len(archive),
                "created_at": snapshot.get("created_at"),
                "updated_at": snapshot.get("updated_at"),
            }
        )
    sessions.sort(
        key=lambda item: float(item.get("updated_at") or item.get("created_at") or 0),
        reverse=True,
    )
    return sessions


def solution_timeline(store: StateStore, session_id: str) -> dict[str, Any]:
    snapshot = store.load_snapshot(session_id)
    final_turn = int(snapshot.get("turn") or 0)
    objective_names = _objective_names(snapshot)
    artifacts = store.list_artifacts(session_id)
    turns: list[dict[str, Any]] = []
    for turn in range(final_turn + 1):
        try:
            event = store.load_event(session_id, turn)
        except KeyError:
            continue
        bundle = _load_optional_json(
            store,
            f"sessions/{session_id}/exports/t{turn:03d}/result_bundle.json",
        )
        names = list(
            ((bundle or {}).get("session") or {}).get("objective_names")
            or (event.get("accepted") or {}).get("objective_names")
            or objective_names
        )
        turns.append(
            _turn_view(
                session_id=session_id,
                turn=turn,
                event=event,
                snapshot=snapshot,
                bundle=bundle,
                objective_names=names,
                artifacts=artifacts,
                is_latest=turn == final_turn,
            )
        )
    return json_safe(
        {
            "schema_version": 1,
            "session": {
                "session_id": snapshot.get("session_id") or session_id,
                "task_id": snapshot.get("task_id"),
                "turn": final_turn,
                "title": _one_line(snapshot.get("initial_problem"), 160),
                "solver_preference": snapshot.get("solver_preference", "auto"),
                "objective_names": objective_names,
                "search": snapshot.get("search") or {},
                "created_at": snapshot.get("created_at"),
                "updated_at": snapshot.get("updated_at"),
            },
            "turns": turns,
        }
    )


def _turn_view(
    *,
    session_id: str,
    turn: int,
    event: dict[str, Any],
    snapshot: dict[str, Any],
    bundle: dict[str, Any] | None,
    objective_names: list[str],
    artifacts: list[str],
    is_latest: bool,
) -> dict[str, Any]:
    accepted = event.get("accepted") or {}
    best = accepted.get("best") or event.get("best")
    solution_set = list((bundle or {}).get("solution_set") or accepted.get("archive") or [])
    final_population = list((bundle or {}).get("final_population") or [])
    history = list(event.get("history") or (bundle or {}).get("iteration_history") or [])
    archive_count = int(
        event.get("archive_count")
        or accepted.get("archive_size")
        or len(solution_set)
        or 0
    )
    population_count = int(
        event.get("population_count")
        or accepted.get("population_size")
        or len(final_population)
        or 0
    )
    restart = event.get("restart_metadata") or {}
    requirement = (
        event.get("problem")
        if turn == 0
        else event.get("natural_language_update")
    ) or (snapshot.get("initial_problem") if turn == 0 else "")
    if not requirement and event.get("kind") == "manual_slot_override":
        requirement = "Manual TSS repair: " + ", ".join(event.get("slot_names") or [])
    turn_prefix = f"sessions/{session_id}/exports/t{turn:03d}/"
    downloads = [
        {
            "name": Path(path).name,
            "url": f"/liveopt-api/artifacts/{path}",
        }
        for path in artifacts
        if path.startswith(turn_prefix) and not path.endswith("ui_result.json")
    ]
    slot_sources: dict[str, str] = {}
    for name, event_key in (("setup.py", "setup_code"), ("fitness.py", "fitness_code")):
        source = event.get(event_key)
        if source is None and is_latest:
            source = (snapshot.get("slots") or {}).get(name)
        if source:
            slot_sources[name] = _bounded_text(source, 24000)
    segments = event.get("segments") or []
    segment_summary = [
        {
            "name": segment.get("name"),
            "kind": segment.get("kind"),
            "length": segment.get("length"),
            "options": len(segment.get("options") or []),
            "values": len(segment.get("values") or []),
        }
        for segment in segments
        if isinstance(segment, dict)
    ]
    best_objectives = list((best or {}).get("objectives") or [])
    feasible = (best or {}).get("feasible")
    conclusion = _conclusion(
        archive_count=archive_count,
        population_count=population_count,
        feasible=feasible,
        objective_names=objective_names,
        objectives=best_objectives,
        restart_skill=restart.get("restart_skill"),
    )
    candidates = solution_set or ([best] if best else [])
    return {
        "turn": turn,
        "update_id": event.get("update_id") or ("t000" if turn == 0 else f"t{turn:03d}"),
        "kind": event.get("kind") or ("initial" if turn == 0 else "update"),
        "requirement": requirement,
        "public_data_patch": event.get("patch_trace", {}).get("public_data_patch")
        or restart.get("data_patch"),
        "restart": {
            "skill": restart.get("restart_skill"),
            "source": restart.get("source"),
            "history_population_ratio": restart.get("realized_history_population_ratio")
            if restart.get("realized_history_population_ratio") is not None
            else restart.get("history_population_ratio"),
            "fresh_population_ratio": restart.get("realized_fresh_population_ratio")
            if restart.get("realized_fresh_population_ratio") is not None
            else restart.get("fresh_population_ratio"),
            "feasible_seed_count": restart.get("feasible_seed_count"),
        },
        "tss": {
            "segments": segment_summary,
            "slots": slot_sources,
            "patch_summary": _patch_summary(event.get("patch_trace")),
        },
        "result": {
            "feasible": feasible,
            "best_objectives": best_objectives,
            "best_solution": (best or {}).get("solution"),
            "archive_count": archive_count,
            "population_count": population_count,
            "generations_completed": _last_generation(history),
            "latency_seconds": event.get("latency_seconds"),
        },
        "conclusion": conclusion,
        "objective_names": objective_names,
        "objective_series": _objective_series(history, objective_names, turn),
        "population_preview": [_plot_point(item) for item in final_population[:1000]],
        "pareto_preview": [_plot_point(item) for item in solution_set[:500]],
        "solution_preview": [
            _solution_row(index, item, objective_names)
            for index, item in enumerate(candidates[:20])
            if isinstance(item, dict)
        ],
        "downloads": downloads,
    }


def _objective_names(snapshot: dict[str, Any]) -> list[str]:
    names = list((snapshot.get("problem_spec") or {}).get("objective_names") or [])
    if names:
        return [str(name) for name in names]
    result = snapshot.get("result") or {}
    candidates = [result.get("best"), *(result.get("archive") or [])]
    width = max((len((item or {}).get("result", {}).get("objectives") or []) for item in candidates), default=0)
    return [f"objective {index + 1}" for index in range(width)]


def _load_optional_json(store: StateStore, path: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(store.resolve_artifact(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, ValueError):
        return None
    return payload if isinstance(payload, dict) else None


def _objective_series(
    history: list[dict[str, Any]], objective_names: list[str], turn: int
) -> list[dict[str, Any]]:
    series: list[dict[str, Any]] = []
    for index, name in enumerate(objective_names or ["objective"]):
        points = []
        for item in history:
            if not isinstance(item, dict):
                continue
            minimum = _indexed_metric(item, "objective_min", index, name)
            if minimum is None:
                continue
            points.append(
                {
                    "generation": item.get("generation"),
                    "minimum": minimum,
                    "mean": _indexed_metric(item, "objective_mean", index, name),
                    "maximum": _indexed_metric(item, "objective_max", index, name),
                    "turn": turn,
                }
            )
        if points:
            series.append({"name": name, "points": points})
    return series


def _indexed_metric(item: dict[str, Any], prefix: str, index: int, name: str) -> Any:
    values = item.get(prefix)
    if isinstance(values, list) and index < len(values):
        return values[index]
    suffix = "".join(character if character.isalnum() else "_" for character in name).strip("_").lower()
    return item.get(f"{prefix}_{suffix or index + 1}")


def _plot_point(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        "solution_index": candidate.get("solution_index"),
        "feasible": candidate.get("feasible"),
        "objectives": list(candidate.get("objectives") or []),
    }


def _solution_row(index: int, candidate: dict[str, Any], objective_names: list[str]) -> dict[str, Any]:
    row: dict[str, Any] = {
        "solution_index": index,
        "feasible": candidate.get("feasible"),
        "scalar": candidate.get("scalar"),
    }
    for objective_index, value in enumerate(candidate.get("objectives") or []):
        name = objective_names[objective_index] if objective_index < len(objective_names) else f"objective {objective_index + 1}"
        row[name] = value
    return row


def _last_generation(history: list[dict[str, Any]]) -> int | None:
    values = [
        int(item["generation"])
        for item in history
        if isinstance(item, dict) and item.get("generation") is not None
    ]
    return max(values) if values else None


def _patch_summary(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    return {
        key: value.get(key)
        for key in (
            "localization",
            "data_patch",
            "patched_slots",
            "repair_attempts",
            "validation",
        )
        if value.get(key) is not None
    }


def _conclusion(
    *,
    archive_count: int,
    population_count: int,
    feasible: Any,
    objective_names: list[str],
    objectives: list[Any],
    restart_skill: str | None,
) -> str:
    status = "a feasible result" if feasible is True else "a result"
    objective_text = ", ".join(
        f"{objective_names[index] if index < len(objective_names) else f'objective {index + 1}'}={value:.5g}"
        if isinstance(value, (int, float))
        else f"{objective_names[index] if index < len(objective_names) else f'objective {index + 1}'}={value}"
        for index, value in enumerate(objectives)
    )
    parts = [f"Accepted {status} with {archive_count} solution-set members from {population_count} final candidates."]
    if objective_text:
        parts.append(f"Representative objectives: {objective_text}.")
    if restart_skill:
        parts.append(f"Dynamic search used {_restart_label(restart_skill)}.")
    return " ".join(parts)


def _restart_label(value: str) -> str:
    return {
        "full_restart_v1": "full restart",
        "warm_restart_v1": "warm restart with repair",
        "population_transfer_v1": "direct population transfer",
    }.get(value, value.replace("_", " "))


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n# ... preview truncated; use the downloadable bundle for the full artifact."


def _one_line(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "..."
