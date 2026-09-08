"""One interactive LiveOpt session: a dynamic runner plus per-turn traces.

This module wires the real paper pipeline (``evo2.agents``) into a stateful
session object. No algorithm is reimplemented here; the session only builds
the LLM client, constructs the agents, and converts their outputs into
JSON-serializable records for the web layer.
"""

from __future__ import annotations

import copy
import difflib
import json
import os
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable

from evo2.agents.llm_client import create_llm_client
from evo2.agents.liveopt_dynamic_impl import (
    LiveOptDataPatcher,
    LiveOptDynamicRunner,
    LiveOptUpdateLocalizer,
    LiveOptWorkbenchPatcher,
    normalize_public_context_tables,
)
from evo2.agents.liveopt_workbench_impl import LiveOptWorkbenchGenerator
from evo2.agents.semantic_restart_gate import LiveOptSemanticRestartGate
from evo2.core.template_optimizer import Candidate, EvolutionConfig, EvolutionResult

ClientFactory = Callable[..., Any]

ARCHIVE_POINT_LIMIT = 50


@contextmanager
def _session_cache_env():
    """Disable the shared on-disk LLM caches for the duration of a call.

    The provider clients and the semantic gate read cache settings from
    ``os.environ`` at call time, so each session push/pops the flags instead
    of relying on global state.
    """

    flags = {"DEEPSEEK_CACHE": "0", "KIMI_CACHE": "0", "LIVEOPT_SEMANTIC_RESTART_CACHE": "0"}
    previous = {key: os.environ.get(key) for key in flags}
    os.environ.update(flags)
    try:
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def build_client(
    *,
    provider: str | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    client_factory: ClientFactory | None = None,
) -> Any:
    """Build the chat client for one session; the api key stays in memory only."""

    kwargs = {"provider": provider, "api_key": api_key, "base_url": base_url, "model": model}
    if client_factory is not None:
        return client_factory(**kwargs)
    return create_llm_client(model=model, provider=provider, api_key=api_key, base_url=base_url)


@dataclass
class DemoSession:
    """One LiveOptDynamicRunner plus accepted history and per-turn traces."""

    session_id: str
    task_id: str
    initial_problem: str
    runner: LiveOptDynamicRunner
    client: Any
    model: str
    population_size: int = 50
    generations: int = 50
    seed: int = 0
    archive_limit: int = 50
    max_repairs: int = 3
    turns: list[dict[str, Any]] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    busy: bool = False

    @classmethod
    def create(
        cls,
        *,
        task_id: str,
        natural_language_problem: str,
        public_context: dict[str, Any],
        provider: str | None = None,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        population_size: int = 50,
        generations: int = 50,
        seed: int = 0,
        archive_limit: int = 50,
        max_repairs: int = 3,
        client_factory: ClientFactory | None = None,
        session_id: str | None = None,
    ) -> "DemoSession":
        """Generate the initial Workbench and run the initial search."""

        with _session_cache_env():
            client = build_client(
                provider=provider,
                api_key=api_key,
                base_url=base_url,
                model=model,
                client_factory=client_factory,
            )
            model_name = model or str(getattr(client, "model", "") or "deepseek-v4-pro")
            context = normalize_public_context_tables(copy.deepcopy(public_context))
            generator = LiveOptWorkbenchGenerator(model=model_name, client=client)
            project = generator.generate_project(
                task_id,
                natural_language_problem,
                context,
                smoke_test=True,
                max_repairs=max_repairs,
            )
            config = EvolutionConfig(
                population_size=population_size,
                generations=generations,
                seed=seed,
                archive_limit=archive_limit,
            )
            initial = project.run(config)
            gate = LiveOptSemanticRestartGate(natural_language_problem, model=model_name, client=client)
            runner = LiveOptDynamicRunner(
                project,
                public_context=context,
                result=initial,
                localizer=LiveOptUpdateLocalizer(model=model_name, client=client),
                data_patcher=LiveOptDataPatcher(model=model_name, client=client),
                patcher=LiveOptWorkbenchPatcher(model=model_name, client=client),
                semantic_restart_gate=gate,
            )
        session = cls(
            session_id=session_id or uuid.uuid4().hex[:12],
            task_id=task_id,
            initial_problem=natural_language_problem,
            runner=runner,
            client=client,
            model=model_name,
            population_size=population_size,
            generations=generations,
            seed=seed,
            archive_limit=archive_limit,
            max_repairs=max_repairs,
        )
        session.turns.append(
            {
                "turn": 0,
                "kind": "initial",
                "best": _candidate_record(initial.best),
                "archive": _archive_points(initial),
                "objective_names": _objective_names(project.problem_spec),
                "usage": _sum_usage(project.trace.usage),
                "latency_seconds": project.trace.latency_seconds,
                "errors": list(project.trace.errors),
                "prompts": list(project.trace.prompts),
                "raw_responses": list(project.trace.raw_responses),
            }
        )
        return session

    @property
    def public_context(self) -> dict[str, Any]:
        return self.runner.public_context

    def apply_update(self, update_id: str | None, text: str) -> dict[str, Any]:
        """Apply one natural-language update and return a JSON-safe summary."""

        turn = len(self.turns)
        update_id = update_id or f"u{turn:03d}"
        previous_slots = dict(self.runner.current_slots)
        config = EvolutionConfig(
            population_size=self.population_size,
            generations=self.generations,
            seed=self.seed + turn,
            archive_limit=self.archive_limit,
        )
        with _session_cache_env():
            stage = self.runner.update(
                update_id=update_id,
                natural_language_update=text,
                config=config,
                max_patch_repairs=self.max_repairs,
            )
        new_slots = {"setup.py": stage.project.setup_code, "fitness.py": stage.project.fitness_code}
        diffs = {
            name: _unified_diff(previous_slots.get(name, ""), new_slots.get(name, ""), name)
            for name in ("setup.py", "fitness.py")
        }
        slots_changed = [name for name, diff in diffs.items() if diff]
        record = _json_safe(stage.to_record())
        record["turn"] = turn
        record["kind"] = "update"
        record["diffs"] = diffs
        self.turns.append(record)

        impact = stage.impact
        restart_metadata = _json_safe(stage.restart_metadata)
        return {
            "turn": turn,
            "update_id": update_id,
            "natural_language_update": text,
            "localization": {
                "data_update": impact.data_update,
                "patch_setup": impact.patch_setup,
                "patch_fitness": impact.patch_fitness,
                "llm_restart_hint": str((impact.raw or {}).get("original_restart_skill") or impact.restart_skill),
                "reason": impact.reason,
            },
            "slots": {
                "changed": slots_changed,
                "diffs": diffs,
                "setup_code": stage.project.setup_code,
                "fitness_code": stage.project.fitness_code,
            },
            "data_patch": _json_safe(restart_metadata.get("data_patch") or {}),
            "restart": {
                "restart_skill": impact.restart_skill,
                "reason": impact.reason,
                "seed_count": len(stage.initial_genomes),
                "metadata": restart_metadata,
            },
            "accepted": {
                "best": _candidate_record(stage.result.best),
                "archive": _archive_points(stage.result),
                "objective_names": _objective_names(stage.project.problem_spec),
            },
            "ledger": _json_safe(copy.deepcopy(self.runner.public_update_history)),
            "usage": _sum_usage(stage.patch_trace.usage),
            "latency_seconds": stage.latency_seconds,
            "errors": list(stage.patch_trace.errors),
        }

    def state_summary(self) -> dict[str, Any]:
        """Compact view of the current live state S_t."""

        project = self.runner.project
        result = self.runner.result
        tables = self.runner.public_context.get("tables") or {}
        return {
            "session_id": self.session_id,
            "task_id": self.task_id,
            "turn": len(self.turns) - 1,
            "model": self.model,
            "objective_names": _objective_names(project.problem_spec),
            "segments": _json_safe([segment.__dict__ for segment in project.segments]),
            "tables": {str(name): {"rows": len(rows) if isinstance(rows, list) else 0} for name, rows in tables.items()},
            "slots": {"setup.py": project.setup_code, "fitness.py": project.fitness_code},
            "accepted": {
                "best": _candidate_record(result.best) if result else None,
                "archive": _archive_points(result) if result else [],
            },
            "ledger": _json_safe(copy.deepcopy(self.runner.public_update_history)),
            "restart_history": [
                {
                    "turn": record["turn"],
                    "update_id": record.get("update_id"),
                    "restart_skill": (record.get("restart_metadata") or {}).get("restart_skill"),
                    "reason": (record.get("impact") or {}).get("reason", ""),
                }
                for record in self.turns
                if record.get("kind") == "update"
            ],
            "usage_total": self._usage_total(),
        }

    def _usage_total(self) -> dict[str, int]:
        entries: list[dict[str, Any]] = []
        for record in self.turns:
            if isinstance(record.get("usage"), dict):  # initial turn stores a summed dict
                entries.append(record["usage"])
            trace = record.get("patch_trace") or {}
            entries.extend(entry for entry in trace.get("usage") or [] if isinstance(entry, dict))
        return _sum_usage(entries)

    def trace_record(self, turn: int) -> dict[str, Any]:
        """Full trace for one turn, including prompts and raw responses."""

        if turn < 0 or turn >= len(self.turns):
            raise KeyError(f"unknown turn: {turn}")
        return _json_safe(self.turns[turn])


def _objective_names(problem_spec: dict[str, Any]) -> list[str]:
    names = problem_spec.get("objective_names") if isinstance(problem_spec, dict) else None
    return [str(name) for name in names or []]


def _candidate_record(candidate: Candidate | None) -> dict[str, Any] | None:
    if candidate is None:
        return None
    result = candidate.result
    return _json_safe(
        {
            "genome": candidate.genome,
            "scalar": result.scalar if result else None,
            "objectives": list(result.objectives or []) if result else [],
            "feasible": result.feasible if result else None,
            "violations": result.violations if result else {},
            "solution": result.solution if result else {},
        }
    )


def _archive_points(result: EvolutionResult, limit: int = ARCHIVE_POINT_LIMIT) -> list[dict[str, Any]]:
    """Objective vectors plus decisions for the accepted front, capped in size."""

    points = []
    for candidate in list(result.archive or [])[: max(1, limit)]:
        fitness = candidate.result
        points.append(
            _json_safe(
                {
                    "objectives": list(fitness.objectives or []) if fitness else [],
                    "scalar": fitness.scalar if fitness else None,
                    "feasible": fitness.feasible if fitness else None,
                    "decision": fitness.solution if fitness else {},
                }
            )
        )
    return points


def _sum_usage(entries: list[dict[str, Any] | None]) -> dict[str, int]:
    totals = {"total_tokens": 0, "prompt_tokens": 0, "completion_tokens": 0, "calls": 0}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        totals["calls"] += 1
        for key in ("total_tokens", "prompt_tokens", "completion_tokens"):
            try:
                totals[key] += int(entry.get(key) or 0)
            except (TypeError, ValueError):
                continue
    return totals


def _unified_diff(old: str, new: str, name: str) -> str:
    if old == new:
        return ""
    lines = difflib.unified_diff(
        old.splitlines(),
        new.splitlines(),
        fromfile=f"a/{name}",
        tofile=f"b/{name}",
        lineterm="",
    )
    return "\n".join(lines)


def _json_safe(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=_json_default))


def _json_default(value: Any) -> Any:
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:  # noqa: BLE001
            pass
    return str(value)
