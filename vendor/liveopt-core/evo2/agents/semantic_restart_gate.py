"""Reference-free semantic gate for LiveOpt Warm-versus-Full decisions."""

from __future__ import annotations

import copy
import fcntl
import hashlib
import json
import os
import time
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from evo2.agents.llm_client import create_llm_client, is_llm_quota_limit_error
from evo2.agents.liveopt_workbench_impl import ScaffoldProject, ScaffoldTrace


SEMANTIC_RESTART_PROMPT_VERSION = "liveopt_semantic_restart_gate_v2"
SEMANTIC_CHANGE_MECHANISMS = frozenset(
    {
        "decision_support_replacement",
        "objective_preference_reversal",
        "constraint_regime_change",
        "resource_role_reversal",
        "distant_basin_risk",
    }
)


@dataclass(frozen=True)
class SemanticRestartDecision:
    reuse_risk: str = "unknown"
    mechanisms: tuple[str, ...] = ()
    verified_mechanisms: tuple[str, ...] = ()
    full_vote: bool = False
    verified_full_vote: bool = False
    evidence_paths: tuple[str, ...] = ()
    verified_evidence_paths: tuple[str, ...] = ()
    reason: str = "semantic gate unavailable"
    model: str = ""
    prompt_version: str = SEMANTIC_RESTART_PROMPT_VERSION
    cache_key: str = ""
    cache_hit: bool = False

    @classmethod
    def from_mapping(
        cls,
        payload: dict[str, Any],
        *,
        model: str,
        cache_key: str,
        allowed_evidence_paths: set[str],
        supported_mechanisms: set[str],
    ) -> "SemanticRestartDecision":
        risk = str(payload.get("reuse_risk") or "unknown").strip().lower()
        if risk not in {"low", "high", "unknown"}:
            risk = "unknown"
        mechanisms = tuple(
            dict.fromkeys(
                str(item).strip()
                for item in list(payload.get("change_mechanisms") or payload.get("mechanisms") or [])
                if str(item).strip() in SEMANTIC_CHANGE_MECHANISMS
            )
        )
        evidence_paths = tuple(
            dict.fromkeys(
                _normalize_evidence_path(item)
                for item in list(payload.get("evidence_paths") or [])
                if _normalize_evidence_path(item)
            )
        )
        verified_paths = tuple(path for path in evidence_paths if path in allowed_evidence_paths)
        verified_mechanisms = tuple(mechanism for mechanism in mechanisms if mechanism in supported_mechanisms)
        full_vote = bool(payload.get("full_vote", False))
        verified_full_vote = bool(
            full_vote
            and risk == "high"
            and verified_mechanisms
            and verified_paths
        )
        return cls(
            reuse_risk=risk,
            mechanisms=mechanisms,
            verified_mechanisms=verified_mechanisms,
            full_vote=full_vote,
            verified_full_vote=verified_full_vote,
            evidence_paths=evidence_paths,
            verified_evidence_paths=verified_paths,
            reason=str(payload.get("reason") or "").strip() or "no semantic explanation",
            model=model,
            cache_key=cache_key,
        )

    @classmethod
    def from_record(cls, payload: dict[str, Any]) -> "SemanticRestartDecision":
        return cls(
            reuse_risk=str(payload.get("reuse_risk") or "unknown"),
            mechanisms=tuple(payload.get("mechanisms") or ()),
            verified_mechanisms=tuple(payload.get("verified_mechanisms") or ()),
            full_vote=bool(payload.get("full_vote", False)),
            verified_full_vote=bool(payload.get("verified_full_vote", False)),
            evidence_paths=tuple(payload.get("evidence_paths") or ()),
            verified_evidence_paths=tuple(payload.get("verified_evidence_paths") or ()),
            reason=str(payload.get("reason") or ""),
            model=str(payload.get("model") or ""),
            prompt_version=str(payload.get("prompt_version") or SEMANTIC_RESTART_PROMPT_VERSION),
            cache_key=str(payload.get("cache_key") or ""),
            cache_hit=bool(payload.get("cache_hit", False)),
        )

    def to_record(self) -> dict[str, Any]:
        return {
            "reuse_risk": self.reuse_risk,
            "mechanisms": list(self.mechanisms),
            "verified_mechanisms": list(self.verified_mechanisms),
            "full_vote": self.full_vote,
            "verified_full_vote": self.verified_full_vote,
            "evidence_paths": list(self.evidence_paths),
            "verified_evidence_paths": list(self.verified_evidence_paths),
            "reason": self.reason,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "cache_key": self.cache_key,
            "cache_hit": self.cache_hit,
        }


class LiveOptSemanticRestartGate:
    """Keep public problem history and cast a cached, evidence-grounded Full vote.

    The complete message prefix is stable across successive updates. Providers
    with automatic prefix/context caching can therefore reuse the initial
    problem and previous update turns. A separate parsed-choice cache prevents
    any provider call when the model, initial problem, history, and current
    public delta are identical.
    """

    def __init__(
        self,
        initial_problem: str,
        *,
        model: str = "deepseek-v4-pro",
        client: Any | None = None,
        cache_dir: str | Path | None = None,
    ):
        self.initial_problem = str(initial_problem or "").strip()
        self.model = model
        self.client = client or create_llm_client(model=model)
        self.cache_dir = Path(cache_dir) if cache_dir is not None else _default_choice_cache_dir()
        self.history: list[dict[str, Any]] = []
        self._decisions_by_turn: dict[str, SemanticRestartDecision] = {}
        self._state_path = self.cache_dir / "state" / f"{_sha256_text(self.initial_problem)}.json"

    def prime_public_history(self, history: list[dict[str, Any]] | None) -> None:
        """Record a replayed public prefix when resuming from saved artifacts."""

        if self.history:
            return
        for item in list(history or []):
            if not isinstance(item, dict):
                continue
            update_id = str(item.get("update_id") or "")
            update_text = str(item.get("natural_language_update") or item.get("public_update") or "")
            prompt = "\n".join(
                [
                    "Previously accepted public update (artifact replay prefix):",
                    _opaque_update_id(update_id),
                    update_text.strip(),
                ]
            )
            response_content = '{"status":"public update stored from replay prefix"}'
            self.history.append(
                {
                    "turn_fingerprint": _stable_hash({"update_id": update_id, "update": update_text}),
                    "update_id": update_id,
                    "natural_language_update": update_text,
                    "prompt": prompt,
                    "response_content": response_content,
                    "digest": {},
                    "decision": SemanticRestartDecision(
                        reuse_risk="unknown",
                        reason="replayed prefix; semantic decision not recomputed",
                        model=self.model,
                    ).to_record(),
                }
            )
        if self.history and _semantic_choice_cache_enabled():
            _atomic_write_json(
                self._state_path,
                {
                    "prompt_version": SEMANTIC_RESTART_PROMPT_VERSION,
                    "model": self.model,
                    "initial_problem": self.initial_problem,
                    "history": self.history,
                },
            )

    def decide(
        self,
        *,
        update_id: str,
        natural_language_update: str,
        previous_public_context: dict[str, Any],
        public_context: dict[str, Any],
        previous_project: ScaffoldProject,
        project: ScaffoldProject,
    ) -> tuple[SemanticRestartDecision, ScaffoldTrace]:
        trace = ScaffoldTrace(model=self.model)
        digest = build_public_change_digest(
            previous_public_context=previous_public_context,
            public_context=public_context,
            previous_project=previous_project,
            project=project,
        )
        current_prompt = build_semantic_restart_prompt(
            update_id=update_id,
            natural_language_update=natural_language_update,
            digest=digest,
        )
        trace.prompts.append(current_prompt)
        turn_fingerprint = _stable_hash(
            {
                "update_id": update_id,
                "natural_language_update": natural_language_update,
                "digest": digest,
            }
        )
        if turn_fingerprint in self._decisions_by_turn:
            decision = replace(self._decisions_by_turn[turn_fingerprint], cache_hit=True)
            trace.usage.append({"total_tokens": 0, "semantic_choice_cache_hits": 1})
            return decision, trace

        messages = self._context_messages(current_prompt)
        cache_key = _stable_hash(
            {
                "prompt_version": SEMANTIC_RESTART_PROMPT_VERSION,
                "model": self.model,
                "messages": messages,
            }
        )
        cache_path = self.cache_dir / "choices" / f"{cache_key}.json"
        lock_path = self.cache_dir / "locks" / f"{cache_key}.lock"
        allowed_paths = set(digest.get("changed_field_paths") or [])
        supported_mechanisms = supported_semantic_mechanisms(digest)
        started = time.perf_counter()
        response_content = ""
        cache_hit = False
        try:
            if _semantic_choice_cache_enabled():
                lock_path.parent.mkdir(parents=True, exist_ok=True)
                with lock_path.open("a+", encoding="utf-8") as lock_handle:
                    fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX)
                    if cache_path.exists():
                        cached = json.loads(cache_path.read_text(encoding="utf-8"))
                        decision = replace(SemanticRestartDecision.from_record(cached["decision"]), cache_hit=True)
                        response_content = str(cached.get("response_content") or "")
                        trace.usage.append({"total_tokens": 0, "semantic_choice_cache_hits": 1})
                        cache_hit = True
                    else:
                        decision, response_content = self._call_model(
                            messages=messages,
                            cache_key=cache_key,
                            allowed_evidence_paths=allowed_paths,
                            supported_mechanisms=supported_mechanisms,
                            trace=trace,
                        )
                        cache_path.parent.mkdir(parents=True, exist_ok=True)
                        _atomic_write_json(
                            cache_path,
                            {"decision": decision.to_record(), "response_content": response_content},
                        )
            else:
                decision, response_content = self._call_model(
                    messages=messages,
                    cache_key=cache_key,
                    allowed_evidence_paths=allowed_paths,
                    supported_mechanisms=supported_mechanisms,
                    trace=trace,
                )
        except Exception as exc:  # noqa: BLE001
            if is_llm_quota_limit_error(exc):
                raise
            trace.errors.append(f"semantic restart gate fallback: {type(exc).__name__}: {exc}")
            decision = SemanticRestartDecision(
                reuse_risk="unknown",
                reason="semantic gate failed; fail closed to Fixed Warm",
                model=self.model,
                cache_key=cache_key,
            )
            response_content = json.dumps(decision.to_record(), ensure_ascii=False, sort_keys=True)
        trace.latency_seconds = time.perf_counter() - started
        trace.raw_responses.append(response_content)
        if cache_hit:
            decision = replace(decision, cache_hit=True)
        self._record_turn(
            turn_fingerprint=turn_fingerprint,
            update_id=update_id,
            natural_language_update=natural_language_update,
            prompt=current_prompt,
            response_content=response_content or json.dumps(decision.to_record(), ensure_ascii=False, sort_keys=True),
            digest=digest,
            decision=decision,
        )
        return decision, trace

    def _call_model(
        self,
        *,
        messages: list[dict[str, str]],
        cache_key: str,
        allowed_evidence_paths: set[str],
        supported_mechanisms: set[str],
        trace: ScaffoldTrace,
    ) -> tuple[SemanticRestartDecision, str]:
        response = self.client.chat(messages, temperature=0.0, max_tokens=1200, json_mode=True)
        trace.usage.append(response.get("usage", {}) if isinstance(response, dict) else {})
        content = (
            response.get("choices", [{}])[0].get("message", {}).get("content", "")
            if isinstance(response, dict)
            else ""
        )
        payload = _extract_json_object(content)
        decision = SemanticRestartDecision.from_mapping(
            payload,
            model=self.model,
            cache_key=cache_key,
            allowed_evidence_paths=allowed_evidence_paths,
            supported_mechanisms=supported_mechanisms,
        )
        return decision, content

    def _context_messages(self, current_prompt: str) -> list[dict[str, str]]:
        messages = [
            {
                "role": "system",
                "content": (
                    "You are the semantic channel of a reference-free dynamic optimization restart gate. "
                    "Use only the supplied public problem and verified public changes. Return one JSON object."
                ),
            },
            {
                "role": "user",
                "content": "Initial public optimization problem:\n" + self.initial_problem,
            },
            {
                "role": "assistant",
                "content": '{"status":"initial public problem stored"}',
            },
        ]
        for turn in self.history:
            messages.append({"role": "user", "content": str(turn["prompt"])})
            messages.append({"role": "assistant", "content": str(turn["response_content"])})
        messages.append({"role": "user", "content": current_prompt})
        return messages

    def _record_turn(
        self,
        *,
        turn_fingerprint: str,
        update_id: str,
        natural_language_update: str,
        prompt: str,
        response_content: str,
        digest: dict[str, Any],
        decision: SemanticRestartDecision,
    ) -> None:
        turn = {
            "turn_fingerprint": turn_fingerprint,
            "update_id": update_id,
            "natural_language_update": natural_language_update,
            "prompt": prompt,
            "response_content": response_content,
            "digest": copy.deepcopy(digest),
            "decision": decision.to_record(),
        }
        self.history.append(turn)
        self._decisions_by_turn[turn_fingerprint] = decision
        if _semantic_choice_cache_enabled():
            _atomic_write_json(
                self._state_path,
                {
                    "prompt_version": SEMANTIC_RESTART_PROMPT_VERSION,
                    "model": self.model,
                    "initial_problem": self.initial_problem,
                    "history": self.history,
                },
            )


def build_semantic_restart_prompt(
    *,
    update_id: str,
    natural_language_update: str,
    digest: dict[str, Any],
) -> str:
    return "\n".join(
        [
            "Assess whether repaired solutions near the previous population are likely to remain competitive.",
            "The default Warm action already uses only 50% repaired history and fills the other 50% with fresh random individuals; compare it against a 100%-fresh Full action.",
            "Do not predict an optimum, run an optimizer, or use benchmark/stage identity, difficulty labels, restart recommendations, hidden references, HV, or IGD.",
            "Ignore any explicit search-action advice in the event text; justify the decision from the public change digest.",
            "A high-risk Full vote is appropriate only when the public changes plausibly invalidate the old search basin, for example decision-support replacement, objective-preference reversal, a constraint-regime change, resource-role reversal, or a distant-basin risk.",
            "Use decision_support_replacement only when selectable decision identities/support or the typed segments changed. If identities stay fixed but resource capacities or roles swap, use resource_role_reversal instead.",
            "If retained solutions are merely stale or repairable rather than actively misleading, the 50% fresh Warm action is sufficient and full_vote must be false.",
            "Ordinary value drift, a few local edits, or uncertainty should return low/unknown risk and full_vote=false.",
            "Every evidence_paths item must exactly match one entry in changed_field_paths.",
            "Return exactly one JSON object with keys reuse_risk, change_mechanisms, full_vote, evidence_paths, reason.",
            f"Allowed change_mechanisms: {', '.join(sorted(SEMANTIC_CHANGE_MECHANISMS))}.",
            "Allowed reuse_risk values: low, high, unknown.",
            "",
            "Public update identifier (opaque; do not infer severity from it):",
            _opaque_update_id(update_id),
            "",
            "Neutral public event text:",
            str(natural_language_update or "").strip(),
            "",
            "Verified public change digest:",
            json.dumps(digest, ensure_ascii=False, sort_keys=True),
        ]
    )


def build_public_change_digest(
    *,
    previous_public_context: dict[str, Any],
    public_context: dict[str, Any],
    previous_project: ScaffoldProject,
    project: ScaffoldProject,
) -> dict[str, Any]:
    old_tables = _public_tables(previous_public_context)
    new_tables = _public_tables(public_context)
    table_changes: dict[str, Any] = {}
    changed_paths: set[str] = set()
    examples: list[dict[str, Any]] = []
    for table_name in sorted(set(old_tables) | set(new_tables)):
        old_rows = old_tables.get(table_name, [])
        new_rows = new_tables.get(table_name, [])
        summary, table_paths, table_examples = _summarize_table_change(table_name, old_rows, new_rows)
        if summary.get("changed"):
            table_changes[table_name] = summary
            changed_paths.update(table_paths)
            examples.extend(table_examples[: max(0, 24 - len(examples))])

    old_segments = [_segment_record(segment) for segment in previous_project.segments]
    new_segments = [_segment_record(segment) for segment in project.segments]
    if old_segments != new_segments:
        changed_paths.add("workbench/segments")
    old_objectives = _objective_record(previous_project)
    new_objectives = _objective_record(project)
    if old_objectives != new_objectives:
        changed_paths.add("workbench/objectives")
    if previous_project.setup_code != project.setup_code:
        changed_paths.add("workbench/setup")
    if previous_project.fitness_code != project.fitness_code:
        changed_paths.add("workbench/fitness")
    return {
        "changed_field_paths": sorted(changed_paths),
        "table_changes": table_changes,
        "representative_public_changes": examples,
        "old_segments": old_segments,
        "new_segments": new_segments,
        "old_objectives": old_objectives,
        "new_objectives": new_objectives,
        "setup_changed": previous_project.setup_code != project.setup_code,
        "fitness_changed": previous_project.fitness_code != project.fitness_code,
    }


def supported_semantic_mechanisms(digest: dict[str, Any]) -> set[str]:
    """Verify that a claimed semantic mechanism has matching public structure."""

    paths = set(digest.get("changed_field_paths") or [])
    table_changes = digest.get("table_changes") if isinstance(digest.get("table_changes"), dict) else {}
    supported: set[str] = set()
    active_replacement = any(
        isinstance(summary, dict)
        and summary.get("active_identity_overlap") is not None
        and float(summary["active_identity_overlap"]) <= 0.5
        for summary in table_changes.values()
    )
    row_replacement = any(
        isinstance(summary, dict)
        and min(int(summary.get("old_row_count") or 0), int(summary.get("new_row_count") or 0)) >= 4
        and float(summary.get("row_identity_overlap", 1.0)) <= 0.5
        for summary in table_changes.values()
    )
    if "workbench/segments" in paths or active_replacement or row_replacement:
        supported.add("decision_support_replacement")

    preference_paths = {path for path in paths if "/preferences/" in path or "/preference" in path}
    policy_paths = {path for path in paths if "/policy/" in path or path == "workbench/fitness"}
    if preference_paths and policy_paths:
        supported.add("objective_preference_reversal")

    constraint_fields = {
        "active",
        "available",
        "availability",
        "capacity",
        "cpu",
        "mem",
        "gpu",
        "gpu_required",
        "max_shifts",
        "required",
        "eligibility",
        "eligible",
        "shift_end",
    }
    changed_constraint_paths = {
        path for path in paths if path.rsplit("/", 1)[-1] in constraint_fields
    }
    if "workbench/segments" in paths or active_replacement or len(changed_constraint_paths) >= 2:
        supported.add("constraint_regime_change")

    resource_tables = ("machines", "vehicles", "nurses", "staff", "resources")
    resource_role_paths = {
        path
        for path in paths
        if any(f"tables/{table}/" in path for table in resource_tables)
        and path.rsplit("/", 1)[-1]
        in {"capacity", "cpu", "mem", "gpu", "emission_rate", "energy_idle", "energy_per_cpu", "max_shifts"}
    }
    if len(resource_role_paths) >= 2:
        supported.add("resource_role_reversal")

    if supported & {
        "decision_support_replacement",
        "objective_preference_reversal",
        "constraint_regime_change",
        "resource_role_reversal",
    }:
        supported.add("distant_basin_risk")
    return supported


def _summarize_table_change(
    table_name: str,
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
) -> tuple[dict[str, Any], set[str], list[dict[str, Any]]]:
    identity_key = _row_identity_key_for_pair(old_rows, new_rows)
    old_map = _row_map(old_rows, identity_key)
    new_map = _row_map(new_rows, identity_key)
    old_ids = set(old_map)
    new_ids = set(new_map)
    added = sorted(new_ids - old_ids)
    removed = sorted(old_ids - new_ids)
    field_counts: dict[str, int] = {}
    examples: list[dict[str, Any]] = []
    paths: set[str] = set()
    for row_id in sorted(old_ids & new_ids):
        old_row = old_map[row_id]
        new_row = new_map[row_id]
        for field in sorted(set(old_row) | set(new_row)):
            if old_row.get(field) == new_row.get(field):
                continue
            field_counts[field] = field_counts.get(field, 0) + 1
            path = f"tables/{table_name}/{field}"
            paths.add(path)
            if len(examples) < 12:
                examples.append(
                    {
                        "path": path,
                        "row": row_id,
                        "old": _compact_value(old_row.get(field)),
                        "new": _compact_value(new_row.get(field)),
                    }
                )
    if added or removed:
        paths.add(f"tables/{table_name}/row_membership")
    active_overlap = None
    if any("active" in row for row in old_rows + new_rows):
        old_active = {row_id for row_id, row in old_map.items() if _as_bool(row.get("active", True))}
        new_active = {row_id for row_id, row in new_map.items() if _as_bool(row.get("active", True))}
        active_overlap = _jaccard(old_active, new_active)
        if old_active != new_active:
            paths.add(f"tables/{table_name}/active")
    changed = bool(paths or len(old_rows) != len(new_rows))
    return (
        {
            "changed": changed,
            "identity_key": identity_key,
            "old_row_count": len(old_rows),
            "new_row_count": len(new_rows),
            "added_row_count": len(added),
            "removed_row_count": len(removed),
            "added_row_examples": added[:8],
            "removed_row_examples": removed[:8],
            "row_identity_overlap": _jaccard(old_ids, new_ids),
            "active_identity_overlap": active_overlap,
            "changed_fields": dict(sorted(field_counts.items())),
        },
        paths,
        examples,
    )


def _public_tables(context: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    raw = context.get("tables") if isinstance(context, dict) else None
    if not isinstance(raw, dict):
        raw = context.get("public_data") if isinstance(context, dict) else None
    if isinstance(raw, dict) and isinstance(raw.get("tables"), dict):
        raw = raw["tables"]
    if not isinstance(raw, dict):
        return {}
    return {
        str(name): [copy.deepcopy(row) for row in rows if isinstance(row, dict)]
        for name, rows in raw.items()
        if isinstance(rows, list)
    }


def _row_identity_key(rows: list[dict[str, Any]]) -> str | None:
    if not rows:
        return None
    common = set(rows[0])
    for row in rows[1:]:
        common.intersection_update(row)
    for key in ("id", "code", "name", "order_id", "job_id", "task_id", "nurse", "machine", "vehicle"):
        if key in common and len({str(row.get(key)) for row in rows}) == len(rows):
            return key
    candidates = sorted(key for key in common if key.endswith("_id") or key.endswith("_code"))
    for key in candidates:
        if len({str(row.get(key)) for row in rows}) == len(rows):
            return key
    return None


def _row_identity_key_for_pair(
    old_rows: list[dict[str, Any]],
    new_rows: list[dict[str, Any]],
) -> str | None:
    old_key = _row_identity_key(old_rows)
    new_key = _row_identity_key(new_rows)
    if old_key and old_key == new_key:
        return old_key
    for key in (old_key, new_key):
        if key and all(key in row for row in old_rows + new_rows):
            if len({str(row.get(key)) for row in old_rows}) == len(old_rows) and len(
                {str(row.get(key)) for row in new_rows}
            ) == len(new_rows):
                return key
    return None


def _row_map(rows: list[dict[str, Any]], identity_key: str | None) -> dict[str, dict[str, Any]]:
    return {
        str(row.get(identity_key)) if identity_key is not None else str(index): row
        for index, row in enumerate(rows)
    }


def _segment_record(segment: Any) -> dict[str, Any]:
    values = list(getattr(segment, "values", None) or [])
    options = list(getattr(segment, "options", None) or [])
    demands = list(getattr(segment, "demands", None) or [])
    resources = list(getattr(segment, "resources", None) or [])
    return {
        "name": str(getattr(segment, "name", "")),
        "kind": str(getattr(segment, "kind", "")),
        "length": int(getattr(segment, "length", 0) or 0),
        "value_count": len(values),
        "option_count": len(options),
        "demand_count": len(demands),
        "resource_count": len(resources),
        "value_examples": [_compact_value(value) for value in values[:8]],
        "demand_examples": [_compact_value(value) for value in demands[:8]],
        "resource_examples": [_compact_value(value) for value in resources[:8]],
        "value_signature": _stable_hash(values),
        "demand_signature": _stable_hash(demands),
        "resource_signature": _stable_hash(resources),
        "allow_none": bool(getattr(segment, "allow_none", False)),
    }


def _objective_record(project: ScaffoldProject) -> dict[str, Any]:
    spec = project.problem_spec if isinstance(project.problem_spec, dict) else {}
    return {
        "solver_mode": str(spec.get("solver_mode") or ""),
        "objective_names": list(spec.get("objective_names") or []),
        "objective_senses": list(spec.get("objective_senses") or []),
    }


def _compact_value(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        text = value if not isinstance(value, str) else value[:120]
        return text
    return json.loads(json.dumps(value, ensure_ascii=False, sort_keys=True, default=str))


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 1.0
    return round(len(left & right) / max(1, len(left | right)), 6)


def _normalize_evidence_path(value: Any) -> str:
    return str(value or "").strip().strip("/")


def _extract_json_object(text: str) -> dict[str, Any]:
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
            raise ValueError("semantic restart gate did not return a JSON object")
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("semantic restart gate response must be a JSON object")
    return payload


def _default_choice_cache_dir() -> Path:
    explicit = os.getenv("LIVEOPT_SEMANTIC_RESTART_CACHE_DIR")
    if explicit:
        return Path(explicit)
    return Path(os.getenv("DEEPSEEK_CACHE_DIR", "outputs/deepseek_cache")) / "semantic_restart_gate"


def _semantic_choice_cache_enabled() -> bool:
    semantic = os.getenv("LIVEOPT_SEMANTIC_RESTART_CACHE", "1").strip().lower()
    provider = os.getenv("DEEPSEEK_CACHE", "1").strip().lower()
    return semantic not in {"0", "false", "no", "off"} and provider not in {"0", "false", "no", "off"}


def _stable_hash(value: Any) -> str:
    stable = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return _sha256_text(stable)


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _opaque_update_id(update_id: str) -> str:
    return "event-" + _sha256_text(str(update_id or ""))[:12]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    temporary.replace(path)
