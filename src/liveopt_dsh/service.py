"""Persistent service boundary around the paper-aligned LiveOpt implementation."""

from __future__ import annotations

import copy
import json
import math
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from evo2.agents.llm_client import create_llm_client, infer_llm_provider
from evo2.agents.liveopt_dynamic_impl import (
    LiveOptDataPatcher,
    LiveOptDynamicRunner,
    LiveOptUpdateLocalizer,
    normalize_public_context_tables,
)
from evo2.agents.liveopt_state_binding import apply_state_bindings
from evo2.agents.liveopt_workbench_impl import (
    LiveOptWorkbenchGenerator,
    ScaffoldTrace,
    compile_scaffold_project,
)
from evo2.agents.semantic_restart_gate import LiveOptSemanticRestartGate
from evo2.core.template_optimizer import Candidate, EvolutionConfig, EvolutionResult

from .config import ServiceConfig
from .compat import (
    StructuredWorkbenchPatcher,
    evolution_progress,
    install_provider_compatibility,
    restart_progress,
    sanitize_code_slot,
)
from .app_settings import load_application_settings, load_deepseek_api_key
from .data_adapter import prepare_public_data
from .documents import prepare_uploaded_documents
from .exports import export_session
from .jobs import JobManager
from .serialization import (
    candidate_summary,
    evolution_from_record,
    evolution_to_record,
    json_safe,
)
from .store import StateStore


ClientFactory = Callable[..., Any]
SNAPSHOT_VERSION = 1
APPLICATION_MODEL = "deepseek-v4-flash"
SOLVER_PREFERENCES = frozenset({"auto", "exact", "evolutionary"})


@dataclass
class SessionRuntime:
    session_id: str
    task_id: str
    initial_problem: str
    provider: str
    model: str
    runner: LiveOptDynamicRunner
    client: Any
    population_size: int
    generations: int
    seed: int
    archive_limit: int
    max_repairs: int
    solver_preference: str = "auto"
    turn: int = 0
    created_at: float = 0.0


class LiveOptService:
    """Asynchronous LiveOpt API used by MCP without changing paper code."""

    def __init__(
        self,
        config: ServiceConfig | None = None,
        *,
        client_factory: ClientFactory | None = None,
    ):
        self.config = config or ServiceConfig.from_env()
        self.config.prepare_environment()
        install_provider_compatibility()
        self.store = StateStore(self.config.state_dir)
        self.jobs = JobManager(self.store, self.config.max_workers)
        self.client_factory = client_factory
        self._runtimes: dict[str, SessionRuntime] = {}
        self._session_locks: dict[str, threading.RLock] = {}
        self._registry_lock = threading.RLock()

    def submit_start(
        self,
        *,
        problem: str,
        public_context: dict[str, Any] | None = None,
        public_context_path: str | None = None,
        prepared_data_id: str | None = None,
        task_id: str | None = None,
        session_id: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        population_size: int = 100,
        generations: int | None = None,
        seed: int = 0,
        archive_limit: int = 200,
        max_repairs: int = 3,
        solver_preference: str = "auto",
    ) -> dict[str, Any]:
        problem = str(problem or "").strip()
        if not problem:
            raise ValueError("problem is required")
        session_id = session_id or uuid.uuid4().hex[:12]
        task_id = task_id or f"liveopt_{session_id}"
        if self.store.session_exists(session_id):
            raise ValueError(f"session already exists: {session_id}")
        context = self._load_public_context(
            public_context, public_context_path, prepared_data_id
        )
        if generations is None:
            generations = int(load_application_settings(self.store.root)["generations"])
        search = _validate_search(
            population_size=population_size,
            generations=generations,
            seed=seed,
            archive_limit=archive_limit,
            max_repairs=max_repairs,
        )
        solver_preference = _validate_solver_preference(solver_preference)
        if self.client_factory is None:
            if provider not in (None, "", "deepseek"):
                raise ValueError("the application runtime is fixed to the DeepSeek Flash provider")
            if model not in (None, "", APPLICATION_MODEL):
                raise ValueError(f"the application runtime is fixed to {APPLICATION_MODEL}")
            resolved_provider = "deepseek"
            resolved_model = APPLICATION_MODEL
        else:
            resolved_model = str(model or self.config.default_model)
            resolved_provider = infer_llm_provider(model=resolved_model, provider=provider)
        request = {
            "problem": problem,
            "public_context": context,
            "task_id": task_id,
            "session_id": session_id,
            "provider": resolved_provider,
            "model": resolved_model,
            "solver_preference": solver_preference,
            **search,
        }
        job = self.jobs.submit(
            kind="start",
            session_id=session_id,
            request=request,
            operation=lambda progress: self._start(request, progress),
        )
        return {"session_id": session_id, "job_id": job.job_id, "status": job.status}

    def submit_update(
        self,
        *,
        session_id: str,
        update: str,
        update_id: str | None = None,
    ) -> dict[str, Any]:
        update = str(update or "").strip()
        if not update:
            raise ValueError("update is required")
        snapshot = self.store.load_snapshot(session_id)
        turn = int(snapshot.get("turn") or 0) + 1
        update_id = update_id or f"t{turn:03d}"
        request = {"session_id": session_id, "update": update, "update_id": update_id}
        job = self.jobs.submit(
            kind="update",
            session_id=session_id,
            request=request,
            operation=lambda progress: self._update(request, progress),
        )
        return {"session_id": session_id, "job_id": job.job_id, "status": job.status}

    def submit_slot_override(
        self,
        *,
        session_id: str,
        setup_code: str | None = None,
        fitness_code: str | None = None,
    ) -> dict[str, Any]:
        """Validate user-edited slots and continue the same accepted session."""

        supplied = {
            name: sanitize_code_slot(value)
            for name, value in {
                "setup.py": setup_code,
                "fitness.py": fitness_code,
            }.items()
            if isinstance(value, str) and value.strip()
        }
        if not supplied:
            raise ValueError("provide setup_code and/or fitness_code")
        self.store.load_snapshot(session_id)
        request = {"session_id": session_id, "slots": supplied}
        job = self.jobs.submit(
            kind="slot_override",
            session_id=session_id,
            request={
                "session_id": session_id,
                "slot_names": sorted(supplied),
            },
            operation=lambda progress: self._override_slots(request, progress),
        )
        return {"session_id": session_id, "job_id": job.job_id, "status": job.status}

    def inspect(
        self,
        *,
        session_id: str | None = None,
        job_id: str | None = None,
        view: str = "summary",
        turn: int | None = None,
    ) -> dict[str, Any]:
        if job_id:
            job = self.jobs.get(job_id)
            if not session_id:
                return job
        if not session_id:
            raise ValueError("session_id or job_id is required")
        if view == "summary":
            result = self._summary_from_snapshot(self.store.load_snapshot(session_id))
        elif view == "trace":
            selected_turn = int(turn if turn is not None else self.store.load_snapshot(session_id)["turn"])
            result = self.store.load_event(session_id, selected_turn)
        elif view == "artifacts":
            result = {"session_id": session_id, "artifacts": self.store.list_artifacts(session_id)}
        elif view == "workbench":
            snapshot = self.store.load_snapshot(session_id)
            result = {
                "session_id": session_id,
                "turn": snapshot["turn"],
                "slots": snapshot["slots"],
                "public_context": snapshot["public_context"],
            }
        else:
            raise ValueError("view must be one of: summary, trace, artifacts, workbench")
        if job_id:
            result = {"job": job, "session": result}
        return result

    def prepare_data(
        self,
        sources: list[dict[str, Any]] | None = None,
        *,
        inline_tables: dict[str, list[dict[str, Any]]] | None = None,
        column_groups: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        return prepare_public_data(
            self.store,
            self.config.workspace_root.resolve(),
            sources,
            inline_tables=inline_tables,
            column_groups=column_groups,
        )

    def prepare_uploads(
        self,
        upload_ids: list[str],
        *,
        inline_tables: dict[str, list[dict[str, Any]]] | None = None,
        column_groups: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Prepare browser-uploaded documents without exposing server paths."""

        return prepare_uploaded_documents(
            self.store,
            upload_ids,
            inline_tables=inline_tables,
            column_groups=column_groups,
        )

    def wait_for_job(
        self,
        job_id: str,
        *,
        timeout_seconds: float = 1800.0,
    ) -> dict[str, Any]:
        timeout = max(1.0, min(float(timeout_seconds), 3600.0))
        deadline = time.monotonic() + timeout
        while True:
            job = self.jobs.get(job_id)
            if job.get("status") in {"succeeded", "failed", "cancelled", "interrupted"}:
                return job
            if time.monotonic() >= deadline:
                return {**job, "wait_timed_out": True}
            time.sleep(0.25)

    def export_results(self, session_id: str) -> dict[str, Any]:
        return export_session(self.store, session_id)

    def cancel(self, job_id: str) -> dict[str, Any]:
        return self.jobs.cancel(job_id)

    def close(self, wait: bool = True) -> None:
        self.jobs.close(wait=wait)

    def _start(
        self, request: dict[str, Any], progress: Callable[..., None]
    ) -> dict[str, Any]:
        session_id = request["session_id"]
        with self._session_lock(session_id):
            if self.store.session_exists(session_id):
                snapshot = self.store.load_snapshot(session_id)
                return {**self._summary_from_snapshot(snapshot), "idempotent": True}
            client = self._create_client(request["provider"], request.get("model"))
            model = str(request.get("model") or getattr(client, "model", "") or APPLICATION_MODEL)
            context = normalize_public_context_tables(copy.deepcopy(request["public_context"]))
            generator = LiveOptWorkbenchGenerator(model=model, client=client)
            progress(
                "generating_workbench",
                message="Generating the TSS Workbench from the public request and data.",
                model=model,
                solver_preference=request["solver_preference"],
            )
            try:
                project = generator.generate_project(
                    request["task_id"],
                    request["problem"],
                    context,
                    skill_summary=_solver_preference_instruction(
                        request["solver_preference"]
                    )
                    + "\n"
                    + _data_driven_workbench_instruction(),
                    smoke_test=True,
                    max_repairs=request["max_repairs"],
                )
            except Exception as exc:
                trace = generator.last_trace
                self.store.save_event(
                    session_id,
                    0,
                    "initial_failed",
                    {
                        "kind": "initial_failed",
                        "turn": 0,
                        "task_id": request["task_id"],
                        "problem": request["problem"],
                        "prompts": trace.prompts,
                        "raw_responses": trace.raw_responses,
                        "usage": trace.usage,
                        "errors": trace.errors,
                        "latency_seconds": trace.latency_seconds,
                        "failure_reason": f"{type(exc).__name__}: {exc}",
                    },
                )
                raise
            _enforce_solver_preference(project.problem_spec, request["solver_preference"])
            mode = _solver_mode(project.problem_spec)
            progress(
                "solving",
                message=_solver_progress_message(mode),
                solver_mode=mode,
                population_size=request["population_size"] if mode != "linear_mip" else 1,
                generations=request["generations"] if mode != "linear_mip" else 0,
                variables=len(
                    (project.problem_spec.get("linear_program_spec") or {}).get(
                        "variables", []
                    )
                ),
                constraints=len(
                    (project.problem_spec.get("linear_program_spec") or {}).get(
                        "constraints", []
                    )
                ),
                solver_time_limit_seconds=(
                    self.config.solver_time_limit_seconds
                    if mode == "linear_mip"
                    else None
                ),
            )
            with evolution_progress(
                lambda metrics: progress(
                    "evolutionary_search",
                    message="Searching the generated Workbench.",
                    solver_mode=mode,
                    **metrics,
                ),
                total_generations=request["generations"],
            ):
                result = project.run(_evolution_config(request, turn=0))
            progress(
                "persisting_state",
                message="Persisting the accepted LiveOpt state.",
                executed_generations=int(
                    result.metadata.get("executed_generations") or 0
                ),
            )
            gate = LiveOptSemanticRestartGate(request["problem"], model=model, client=client)
            runner = LiveOptDynamicRunner(
                project,
                public_context=context,
                result=result,
                localizer=LiveOptUpdateLocalizer(model=model, client=client),
                data_patcher=LiveOptDataPatcher(model=model, client=client),
                patcher=StructuredWorkbenchPatcher(model=model, client=client),
                semantic_restart_gate=gate,
            )
            runtime = SessionRuntime(
                session_id=session_id,
                task_id=request["task_id"],
                initial_problem=request["problem"],
                provider=request["provider"],
                model=model,
                runner=runner,
                client=client,
                population_size=request["population_size"],
                generations=request["generations"],
                seed=request["seed"],
                archive_limit=request["archive_limit"],
                max_repairs=request["max_repairs"],
                solver_preference=request["solver_preference"],
                turn=0,
                created_at=time.time(),
            )
            event = {
                "kind": "initial",
                "turn": 0,
                "task_id": runtime.task_id,
                "problem": runtime.initial_problem,
                "prompts": project.trace.prompts,
                "raw_responses": project.trace.raw_responses,
                "usage": project.trace.usage,
                "errors": project.trace.errors,
                "latency_seconds": project.trace.latency_seconds,
                "history": json_safe(result.history),
                "setup_code": project.setup_code,
                "fitness_code": project.fitness_code,
                "segments": json_safe(project.segments),
                "accepted": self._accepted(result, project.problem_spec),
            }
            event_path = self.store.save_event(session_id, 0, "initial", event)
            snapshot = self._snapshot(runtime)
            self.store.save_snapshot(session_id, snapshot)
            with self._registry_lock:
                self._runtimes[session_id] = runtime
            return {
                **self._summary_from_snapshot(snapshot),
                "trace_path": str(event_path.relative_to(self.config.state_dir.resolve())),
            }

    def _override_slots(
        self, request: dict[str, Any], progress: Callable[..., None]
    ) -> dict[str, Any]:
        session_id = request["session_id"]
        with self._session_lock(session_id):
            runtime = self._runtime(session_id)
            merged_slots = dict(runtime.runner.current_slots)
            merged_slots.update(request["slots"])
            trace = ScaffoldTrace(model="manual_slot_override")
            progress(
                "validating_override",
                message="Validating the edited Workbench slots against the accepted public state.",
                slot_names=sorted(request["slots"]),
            )
            project = compile_scaffold_project(
                runtime.task_id,
                runtime.runner.public_context,
                merged_slots,
                trace,
            )
            persisted_bindings = list(
                (runtime.runner.project.problem_spec or {}).get("state_bindings") or []
            )
            project = apply_state_bindings(project, persisted_bindings)
            _enforce_solver_preference(project.problem_spec, runtime.solver_preference)
            next_turn = runtime.turn + 1
            initial_genomes = None
            if _segments_compatible(runtime.runner.project.segments, project.segments):
                initial_genomes = [
                    copy.deepcopy(candidate.genome)
                    for candidate in runtime.runner.result.population
                ]
            mode = _solver_mode(project.problem_spec)
            progress(
                "solving",
                message="Running the validated Workbench on the accepted public state.",
                solver_mode=mode,
                reused_population=bool(initial_genomes),
            )
            with evolution_progress(
                lambda metrics: progress(
                    "evolutionary_search",
                    message="Searching the manually repaired Workbench.",
                    turn=next_turn,
                    **metrics,
                ),
                total_generations=runtime.generations,
            ):
                result = project.run(
                    _evolution_config(runtime.__dict__, turn=next_turn),
                    initial_genomes=initial_genomes,
                )
            runtime.runner.project = project
            runtime.runner.current_slots = {
                "setup.py": project.setup_code,
                "fitness.py": project.fitness_code,
            }
            runtime.runner.result = result
            runtime.turn = next_turn
            event = {
                "kind": "manual_slot_override",
                "turn": next_turn,
                "slot_names": sorted(request["slots"]),
                "reused_population": bool(initial_genomes),
                "history": json_safe(result.history),
                "setup_code": project.setup_code,
                "fitness_code": project.fitness_code,
                "segments": json_safe(project.segments),
                "accepted": self._accepted(result, project.problem_spec),
            }
            event_path = self.store.save_event(
                session_id, next_turn, "manual_slot_override", event
            )
            snapshot = self._snapshot(runtime)
            self.store.save_snapshot(session_id, snapshot)
            return {
                **self._summary_from_snapshot(snapshot),
                "slot_names": sorted(request["slots"]),
                "trace_path": str(event_path.relative_to(self.config.state_dir.resolve())),
            }

    def _update(
        self, request: dict[str, Any], progress: Callable[..., None]
    ) -> dict[str, Any]:
        session_id = request["session_id"]
        with self._session_lock(session_id):
            runtime = self._runtime(session_id)
            for item in runtime.runner.public_update_history:
                if str(item.get("update_id")) != request["update_id"]:
                    continue
                if str(item.get("natural_language_update")) != request["update"]:
                    raise ValueError(
                        f"update_id {request['update_id']} already exists with different text"
                    )
                return {**self._summary_from_snapshot(self.store.load_snapshot(session_id)), "idempotent": True}
            next_turn = runtime.turn + 1
            progress(
                "adapting_and_solving",
                message="Grounding the update against accepted state before selecting restart and reuse.",
                turn=next_turn,
                solver_preference=runtime.solver_preference,
            )
            with restart_progress(
                lambda details: progress(
                    "restart_selected",
                    message=_restart_progress_message(details),
                    turn=next_turn,
                    **details,
                )
            ), evolution_progress(
                    lambda metrics: progress(
                        "evolutionary_search",
                        message="Searching the updated Workbench with the selected restart state.",
                        turn=next_turn,
                        **metrics,
                    ),
                    total_generations=runtime.generations,
                ):
                stage = runtime.runner.update(
                    update_id=request["update_id"],
                    natural_language_update=request["update"],
                    config=_evolution_config(runtime.__dict__, turn=next_turn),
                    max_patch_repairs=runtime.max_repairs,
                )
            _enforce_solver_preference(
                stage.project.problem_spec, runtime.solver_preference
            )
            progress(
                "persisting_state",
                message="Persisting the accepted updated state.",
                executed_generations=int(
                    stage.result.metadata.get("executed_generations") or 0
                ),
            )
            runtime.turn = next_turn
            event = json_safe(stage.to_record())
            event["kind"] = "update"
            event["turn"] = next_turn
            event_path = self.store.save_event(
                session_id, next_turn, request["update_id"], event
            )
            snapshot = self._snapshot(runtime)
            self.store.save_snapshot(session_id, snapshot)
            return {
                **self._summary_from_snapshot(snapshot),
                "update_id": request["update_id"],
                "restart_skill": stage.impact.restart_skill,
                "restart_reason": stage.impact.reason,
                "trace_path": str(event_path.relative_to(self.config.state_dir.resolve())),
            }

    def _runtime(self, session_id: str) -> SessionRuntime:
        with self._registry_lock:
            runtime = self._runtimes.get(session_id)
        if runtime is not None:
            return runtime
        snapshot = self.store.load_snapshot(session_id)
        if self.client_factory is None:
            provider = "deepseek"
            model = APPLICATION_MODEL
        else:
            provider = snapshot["provider"]
            model = snapshot["model"]
        client = self._create_client(provider, model)
        trace = ScaffoldTrace(model=model)
        project = compile_scaffold_project(
            snapshot["task_id"],
            snapshot["public_context"],
            snapshot["slots"],
            trace,
        )
        persisted_bindings = list(
            (snapshot.get("problem_spec") or {}).get("state_bindings") or []
        )
        project = apply_state_bindings(project, persisted_bindings)
        result = evolution_from_record(snapshot["result"])
        gate = LiveOptSemanticRestartGate(
            snapshot["initial_problem"], model=model, client=client
        )
        history = list(snapshot.get("public_update_history") or [])
        gate.prime_public_history(history)
        runner = LiveOptDynamicRunner(
            project,
            public_context=snapshot["public_context"],
            result=result,
            localizer=LiveOptUpdateLocalizer(model=model, client=client),
            data_patcher=LiveOptDataPatcher(model=model, client=client),
            patcher=StructuredWorkbenchPatcher(model=model, client=client),
            semantic_restart_gate=gate,
            public_update_history=history,
        )
        search = snapshot["search"]
        runtime = SessionRuntime(
            session_id=session_id,
            task_id=snapshot["task_id"],
            initial_problem=snapshot["initial_problem"],
            provider=provider,
            model=model,
            runner=runner,
            client=client,
            population_size=int(search["population_size"]),
            generations=int(search["generations"]),
            seed=int(search["seed"]),
            archive_limit=int(search["archive_limit"]),
            max_repairs=int(search["max_repairs"]),
            solver_preference=str(snapshot.get("solver_preference") or "auto"),
            turn=int(snapshot["turn"]),
            created_at=float(snapshot["created_at"]),
        )
        with self._registry_lock:
            self._runtimes[session_id] = runtime
        return runtime

    def _snapshot(self, runtime: SessionRuntime) -> dict[str, Any]:
        return {
            "schema_version": SNAPSHOT_VERSION,
            "session_id": runtime.session_id,
            "task_id": runtime.task_id,
            "initial_problem": runtime.initial_problem,
            "provider": runtime.provider,
            "model": runtime.model,
            "solver_preference": runtime.solver_preference,
            "turn": runtime.turn,
            "created_at": runtime.created_at,
            "updated_at": time.time(),
            "search": {
                "population_size": runtime.population_size,
                "generations": runtime.generations,
                "seed": runtime.seed,
                "archive_limit": runtime.archive_limit,
                "max_repairs": runtime.max_repairs,
            },
            "public_context": json_safe(runtime.runner.public_context),
            "slots": json_safe(runtime.runner.current_slots),
            "problem_spec": json_safe(runtime.runner.project.problem_spec),
            "result": evolution_to_record(runtime.runner.result),
            "public_update_history": json_safe(runtime.runner.public_update_history),
        }

    def _summary_from_snapshot(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        result = evolution_from_record(snapshot["result"])
        spec = snapshot.get("problem_spec") or {}
        return {
            "session_id": snapshot["session_id"],
            "task_id": snapshot["task_id"],
            "turn": snapshot["turn"],
            "provider": snapshot["provider"],
            "model": snapshot["model"],
            "solver_preference": snapshot.get("solver_preference", "auto"),
            "cache_mode": self.config.cache_mode,
            "objective_names": list(spec.get("objective_names") or []),
            "accepted": self._accepted(result, spec),
            "update_count": len(snapshot.get("public_update_history") or []),
        }

    def _accepted(self, result: EvolutionResult, spec: dict[str, Any]) -> dict[str, Any]:
        limit = self.config.max_result_archive
        return {
            "best": candidate_summary(result.best),
            "archive": [candidate_summary(item) for item in list(result.archive or [])[:limit]],
            "archive_size": len(result.archive or []),
            "population_size": len(result.population or []),
            "objective_names": list(spec.get("objective_names") or []),
        }

    def _create_client(self, provider: str, model: str | None) -> Any:
        if self.client_factory is not None:
            return self.client_factory(provider=provider, model=model, api_key=None, base_url=None)
        api_key = load_deepseek_api_key()
        if not api_key:
            raise ValueError("DeepSeek API key is not configured; add it in LiveOpt Settings")
        return create_llm_client(model=model, provider=provider, api_key=api_key)

    def _load_public_context(
        self,
        public_context: dict[str, Any] | None,
        public_context_path: str | None,
        prepared_data_id: str | None,
    ) -> dict[str, Any]:
        provided = sum(
            value is not None and value != ""
            for value in (public_context, public_context_path, prepared_data_id)
        )
        if provided != 1:
            raise ValueError(
                "provide exactly one of public_context, public_context_path, or prepared_data_id"
            )
        if prepared_data_id:
            prepared = self.store.load_prepared_data(prepared_data_id)
            public_context = prepared.get("public_context")
        if public_context_path:
            path = self.store.resolve_public_path(
                public_context_path, self.config.workspace_root
            )
            payload = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("public_context_path must contain one JSON object")
            public_context = payload.get("public_context", payload)
        if not isinstance(public_context, dict):
            raise ValueError("public_context must be a JSON object")
        return normalize_public_context_tables(copy.deepcopy(public_context))

    def _session_lock(self, session_id: str) -> threading.RLock:
        with self._registry_lock:
            return self._session_locks.setdefault(session_id, threading.RLock())


def _validate_search(**values: int) -> dict[str, int]:
    bounds = {
        "population_size": (2, 10_000),
        "generations": (1, 10_000),
        "seed": (0, 2**31 - 1),
        "archive_limit": (1, 100_000),
        "max_repairs": (0, 10),
    }
    result: dict[str, int] = {}
    for name, value in values.items():
        value = int(value)
        lower, upper = bounds[name]
        if value < lower or value > upper:
            raise ValueError(f"{name} must be between {lower} and {upper}")
        result[name] = value
    return result


def _validate_solver_preference(value: str) -> str:
    preference = str(value or "auto").strip().lower()
    if preference not in SOLVER_PREFERENCES:
        raise ValueError(
            "solver_preference must be one of: "
            + ", ".join(sorted(SOLVER_PREFERENCES))
        )
    return preference


def _solver_mode(problem_spec: dict[str, Any]) -> str:
    solver = problem_spec.get("solver")
    raw = problem_spec.get("solver_mode")
    if raw is None and isinstance(solver, dict):
        raw = solver.get("mode") or solver.get("type")
    return str(raw or "auto").strip().lower()


def _solver_preference_instruction(preference: str) -> str:
    if preference == "exact":
        return (
            "Application solver choice: Exact Solver. Build a domain-neutral "
            "linear_program_spec and set solver_mode='linear_mip'. Do not replace "
            "the requested exact solve with enumeration or evolutionary search. "
            "For variables indexed by public entities, include an explicit "
            "solution_extraction id_map or variables [{var, id}] mapping so the "
            "returned solution uses public entity IDs rather than variable indices."
        )
    if preference == "evolutionary":
        return (
            "Application solver choice: Evolutionary Search. Define composable typed "
            "segments and evaluate(genome, data); select scalar_ga for one objective "
            "or moea for Pareto objectives. Do not emit linear_mip or exact_enumeration."
        )
    return (
        "Application solver choice: Auto. Select linear_mip for a valid linear exact "
        "formulation, scalar_ga for scalar nonlinear/combinatorial search, or moea for "
        "Pareto search."
    )


def _data_driven_workbench_instruction() -> str:
    return (
        "Application public-data contract: every finite public entity collection and "
        "every mutable entity parameter must be read by looping over public_context "
        "tables. Never embed entity identifiers, per-entity tuples, or a fixed resource "
        "list in setup.py or fitness.py. Derive segment domains and lookup maps from table "
        "rows so row additions, removals, and active/eligible changes can be applied as "
        "data-only updates and recompiled without generating new Python source. Repeated "
        "wide columns may already be relationalized into a public association table; use "
        "that table directly. Build violations as a sparse dictionary: omit satisfied or "
        "zero-valued constraints and include only active positive violations."
    )


def _enforce_solver_preference(
    problem_spec: dict[str, Any], preference: str
) -> None:
    mode = _solver_mode(problem_spec)
    if preference == "exact" and mode != "linear_mip":
        raise ValueError(
            f"Exact Solver was requested, but the Workbench produced solver_mode={mode!r}"
        )
    if preference == "evolutionary" and mode in {
        "linear_mip",
        "exact_enumeration",
    }:
        raise ValueError(
            "Evolutionary Search was requested, but the Workbench produced "
            f"solver_mode={mode!r}"
        )


def _solver_progress_message(mode: str) -> str:
    if mode == "linear_mip":
        return "Solving the generated LP/MILP model with the exact-solver backend."
    if mode == "moea":
        return "Running typed Pareto evolutionary search."
    return "Running typed scalar evolutionary search."


def _restart_progress_message(details: dict[str, Any]) -> str:
    skill = str(details.get("restart_skill") or "")
    reused = int(details.get("reused_solution_count") or 0)
    if skill == "full_restart_v1":
        return "Full restart selected: no previous solutions are reused; search starts from a fresh population."
    if skill == "population_transfer_v1":
        return f"Population transfer selected: directly reusing {reused} compatible previous solutions."
    if skill == "warm_restart_v1":
        return f"Warm restart selected: reusing and repairing {reused} previous solutions, then filling fresh seeds."
    return f"Restart selected: {skill or 'runtime default'}; {reused} previous solutions are reusable."


def _evolution_config(values: dict[str, Any], *, turn: int) -> EvolutionConfig:
    return EvolutionConfig(
        population_size=int(values["population_size"]),
        generations=int(values["generations"]),
        seed=int(values["seed"]) + int(turn),
        archive_limit=int(values["archive_limit"]),
        record_metric_history=True,
        history_interval=1,
        history_metric_recorder=_objective_history_metrics,
    )


def _objective_history_metrics(
    _generation: int,
    population: list[Candidate],
    archive: list[Candidate],
    _multi: bool,
) -> dict[str, Any]:
    source = [
        candidate
        for candidate in (archive or population)
        if candidate.result is not None and candidate.result.feasible
    ]
    if not source:
        source = [candidate for candidate in population if candidate.result is not None]
    vectors = [list(candidate.result.objectives or []) for candidate in source]
    width = max((len(vector) for vector in vectors), default=0)
    if width == 0:
        scalars = [
            float(candidate.result.scalar)
            for candidate in source
            if candidate.result is not None
            and math.isfinite(float(candidate.result.scalar))
        ]
        vectors = [[value] for value in scalars]
        width = 1 if vectors else 0
    columns = [
        [
            float(vector[index])
            for vector in vectors
            if index < len(vector) and math.isfinite(float(vector[index]))
        ]
        for index in range(width)
    ]
    return {
        "objective_min": [min(column) if column else None for column in columns],
        "objective_mean": [
            sum(column) / len(column) if column else None for column in columns
        ],
        "objective_max": [max(column) if column else None for column in columns],
        "metric_candidate_count": len(source),
    }


def _segments_compatible(left: list[Any], right: list[Any]) -> bool:
    def signature(segment: Any) -> tuple[Any, ...]:
        return (
            getattr(segment, "name", None),
            getattr(segment, "kind", None),
            int(getattr(segment, "length", 0) or 0),
            tuple(getattr(segment, "demands", []) or []),
            tuple(getattr(segment, "resources", []) or []),
            tuple(getattr(segment, "options", []) or []),
            bool(getattr(segment, "allow_none", False)),
        )

    return [signature(segment) for segment in left] == [
        signature(segment) for segment in right
    ]
