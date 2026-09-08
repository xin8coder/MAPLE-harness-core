"""Compact LiveOpt MCP surface for DeepSeek Harness."""

from __future__ import annotations

import argparse
import atexit
from typing import Any, Literal

from mcp.server import MCPServer

from .service import LiveOptService


server = MCPServer("LiveOpt")
_service: LiveOptService | None = None


def get_service() -> LiveOptService:
    global _service
    if _service is None:
        _service = LiveOptService()
        atexit.register(_service.close)
    return _service


@server.tool()
def liveopt_start(
    problem: str,
    public_context: dict[str, Any] | None = None,
    public_context_path: str | None = None,
    prepared_data_id: str | None = None,
    task_id: str | None = None,
    session_id: str | None = None,
    solver_preference: Literal["auto", "exact", "evolutionary"] = "auto",
    population_size: int = 100,
    generations: int | None = None,
    seed: int = 0,
    archive_limit: int = 200,
    max_repairs: int = 3,
) -> dict[str, Any]:
    """Start one persistent LiveOpt problem; omitted generations use LiveOpt Settings (default 100)."""

    return get_service().submit_start(
        problem=problem,
        public_context=public_context,
        public_context_path=public_context_path,
        prepared_data_id=prepared_data_id,
        task_id=task_id,
        session_id=session_id,
        solver_preference=solver_preference,
        population_size=population_size,
        generations=generations,
        seed=seed,
        archive_limit=archive_limit,
        max_repairs=max_repairs,
    )


@server.tool()
def liveopt_prepare_data(
    sources: list[dict[str, Any]] | None = None,
    inline_tables: dict[str, list[dict[str, Any]]] | None = None,
    column_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prepare files or inline records; optionally relationalize repeated wide columns."""

    return get_service().prepare_data(
        sources,
        inline_tables=inline_tables,
        column_groups=column_groups,
    )


@server.tool()
def liveopt_prepare_uploads(
    upload_ids: list[str],
    inline_tables: dict[str, list[dict[str, Any]]] | None = None,
    column_groups: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Prepare browser-uploaded documents or tables and return one public-data id."""

    return get_service().prepare_uploads(
        upload_ids,
        inline_tables=inline_tables,
        column_groups=column_groups,
    )


@server.tool()
def liveopt_update(
    session_id: str,
    update: str,
    update_id: str | None = None,
) -> dict[str, Any]:
    """Apply one natural-language update to an existing accepted LiveOpt state."""

    return get_service().submit_update(
        session_id=session_id, update=update, update_id=update_id
    )


@server.tool()
def liveopt_override_slots(
    session_id: str,
    setup_code: str | None = None,
    fitness_code: str | None = None,
) -> dict[str, Any]:
    """Validate user-edited setup/fitness code and continue the same accepted session."""

    return get_service().submit_slot_override(
        session_id=session_id,
        setup_code=setup_code,
        fitness_code=fitness_code,
    )


@server.tool()
def liveopt_inspect(
    session_id: str | None = None,
    job_id: str | None = None,
    view: str = "summary",
    turn: int | None = None,
) -> dict[str, Any]:
    """Inspect a job, accepted state, Workbench, artifact list, or one turn trace."""

    return get_service().inspect(
        session_id=session_id, job_id=job_id, view=view, turn=turn
    )


@server.tool()
def liveopt_wait(
    job_id: str,
    timeout_seconds: float = 1800.0,
) -> dict[str, Any]:
    """Wait silently for one LiveOpt job while the dedicated UI shows live progress."""

    return get_service().wait_for_job(job_id, timeout_seconds=timeout_seconds)


@server.tool()
def liveopt_export(session_id: str) -> dict[str, Any]:
    """Export CSV iteration history, the accepted solution set, JSON, and a ZIP bundle."""

    exported = get_service().export_results(session_id)
    return {
        "session_id": exported["session_id"],
        "turn": exported["turn"],
        "objective_names": exported["objective_names"],
        "solution_count": exported["solution_count"],
        "population_count": exported["population_count"],
        "downloads": exported["downloads"],
        "result_url": (
            f"/liveopt-api/results/{session_id}?turn={int(exported['turn'])}"
        ),
    }


@server.tool()
def liveopt_cancel(job_id: str) -> dict[str, Any]:
    """Cancel a queued job; running optimization commits cannot be interrupted safely."""

    return get_service().cancel(job_id)


def main() -> None:
    parser = argparse.ArgumentParser(description="LiveOpt MCP sidecar")
    parser.add_argument(
        "--transport", choices=("stdio", "streamable-http"), default="stdio"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    try:
        if args.transport == "stdio":
            server.run(transport="stdio")
        else:
            server.run(transport="streamable-http", host=args.host, port=args.port)
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
