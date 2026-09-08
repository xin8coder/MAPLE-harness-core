"""Chat-first agent layer for the LiveOpt demo.

A chat holds a message history plus at most one live ``DemoSession``. Every
user message goes through an LLM router that picks one of three tools —
``answer`` (plain conversation), ``start_optimization`` (create a LiveOpt
session), ``apply_update`` (patch the live session) — with a deterministic
fallback when the router fails or is ambiguous. Tool results are summarized
by the LLM (again with a template fallback) and attached to the assistant
message as structured artifact cards.

Chats persist as JSON files (default ``~/.liveopt_demo/chats/``). API keys
are never persisted: settings are redacted before saving. LiveOpt runner
state cannot be serialized, so chats with an optimization session are
restored with ``needs_reinit=True`` plus the original init spec for a
one-click re-initialization.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from demo.episode_upload import (
    EpisodeInput,
    freeform_episode,
    load_builtin_episode,
    load_uploaded_episode,
)
from demo.ingest import (
    IngestError,
    ingest_files_and_goal,
    load_imported_episode,
    preview_card,
)
from demo.session import ClientFactory, DemoSession, _json_safe
from demo.viz import result_image_cards

ROUTER_SYSTEM = """You are the router for a LiveOpt chat agent. LiveOpt is a dynamic optimization system: it builds an optimization Workbench from a natural-language problem, solves it, and applies later natural-language updates.

Decide what to do with the user's latest message. Return exactly one JSON object with keys:
- action: "answer" | "start_optimization" | "apply_update" | "import_data"
- problem: for start_optimization only, the complete natural-language problem description (including every table and number the user provided)
- update: for apply_update only, the exact update text
- goal: for import_data only, the user's optimization goal in one or two sentences

Rules:
- If an optimization session is active and the message describes any change to data, objectives, constraints, or availability, choose apply_update.
- If the user pastes data (tables, CSV, JSON) or refers to uploaded files and wants them optimized, choose import_data.
- If no optimization session is active and the user asks to solve, plan, schedule, or optimize something (without providing data files/tables to convert), choose start_optimization.
- Questions, explanations, and small talk choose answer, even when an optimization session is active.
- When in doubt, choose answer."""

SUMMARIZER_SYSTEM = """You summarize the result of a LiveOpt tool call for the user in 1-3 short sentences.
Mention the committed plan headline (objective value, feasibility) and the restart action when present.
Do not repeat raw JSON; write plain English."""

ASSISTANT_SYSTEM = (
    "You are LiveOpt Assistant, a helpful conversational agent built on the LiveOpt dynamic "
    "optimization stack. Answer clearly and concisely. When the user wants to optimize, plan, or "
    "schedule something, invite them to describe the problem (with any data tables) so you can "
    "start an optimization session."
)

TOOL_ACTIONS = {"answer", "start_optimization", "apply_update", "import_data"}
SECRET_SETTING_KEYS = {"api_key", "apikey", "api-key"}
HISTORY_LIMIT = 40


def default_data_dir() -> Path:
    explicit = os.getenv("LIVEOPT_DEMO_DATA_DIR", "").strip()
    if explicit:
        return Path(explicit)
    return Path.home() / ".liveopt_demo" / "chats"


@dataclass
class Chat:
    chat_id: str
    title: str = "New chat"
    settings: dict[str, Any] = field(default_factory=dict)
    messages: list[dict[str, Any]] = field(default_factory=list)
    optimization_spec: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    session: DemoSession | None = field(default=None, repr=False)
    needs_reinit: bool = False
    _client: Any = field(default=None, repr=False)

    @property
    def has_live_session(self) -> bool:
        return self.session is not None

    def touch(self) -> None:
        self.updated_at = time.time()

    def summary(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "title": self.title,
            "updated_at": self.updated_at,
            "message_count": len(self.messages),
            "has_optimization": self.optimization_spec is not None,
            "live_session": self.has_live_session,
            "needs_reinit": self.needs_reinit,
        }

    def to_record(self) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "title": self.title,
            "settings": redact_settings(self.settings),
            "messages": self.messages,
            "optimization_spec": self.optimization_spec,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_record(cls, record: dict[str, Any]) -> "Chat":
        chat = cls(
            chat_id=str(record["chat_id"]),
            title=str(record.get("title") or "New chat"),
            settings=dict(record.get("settings") or {}),
            messages=list(record.get("messages") or []),
            optimization_spec=record.get("optimization_spec"),
            created_at=float(record.get("created_at") or time.time()),
            updated_at=float(record.get("updated_at") or time.time()),
        )
        # Runner state is not serializable: the message history is restored,
        # the optimization session is marked for one-click re-initialization.
        chat.needs_reinit = chat.optimization_spec is not None
        return chat


def redact_settings(settings: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in settings.items() if key.lower() not in SECRET_SETTING_KEYS and value not in (None, "")}


def merge_settings(base: dict[str, Any], override: dict[str, Any] | None) -> dict[str, Any]:
    merged = dict(base)
    for key, value in (override or {}).items():
        if value not in (None, ""):
            merged[key] = value
    return merged


# Server-side defaults; chats may override per-conversation.  The API key is
# never defaulted here: clients fall back to provider env vars when unset.
DEFAULT_SETTINGS = {
    "provider": os.environ.get("LIVEOPT_DEMO_PROVIDER", "kimi"),
    "model": os.environ.get("LIVEOPT_DEMO_MODEL", "k3"),
}


def effective_settings(chat: "Chat") -> dict[str, Any]:
    """Chat settings with server defaults applied.

    Older or partially-specified chats may carry a provider without a model;
    without this merge the client would fall back to provider env vars (e.g.
    KIMI_MODEL) whose values may not be valid API model ids.
    """
    return merge_settings(DEFAULT_SETTINGS, chat.settings)


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
            raise ValueError("router did not return a JSON object") from None
        payload = json.loads(stripped[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("router response must be a JSON object")
    return payload


def _chat_content(response: Any) -> str:
    if isinstance(response, dict):
        return str(response.get("choices", [{}])[0].get("message", {}).get("content", "") or "")
    return ""


def fallback_route(text: str, has_session: bool) -> dict[str, Any]:
    """Deterministic route when the LLM router fails or is ambiguous."""

    if has_session:
        return {"action": "apply_update", "update": text, "routed_by": "fallback"}
    return {"action": "answer", "routed_by": "fallback"}


def route_message(client: Any, text: str, *, has_session: bool) -> dict[str, Any]:
    prompt = (
        f"Optimization session active: {'yes' if has_session else 'no'}\n\n"
        f"User message:\n{text}"
    )
    try:
        response = client.chat(
            [
                {"role": "system", "content": ROUTER_SYSTEM},
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
            max_tokens=800,
        )
        payload = _extract_json_object(_chat_content(response))
        action = str(payload.get("action") or "").strip()
        if action not in TOOL_ACTIONS:
            raise ValueError(f"unsupported router action: {action!r}")
        if action == "start_optimization" and not has_session and not str(payload.get("problem") or "").strip():
            payload["problem"] = text
        if action == "apply_update" and not str(payload.get("update") or "").strip():
            payload["update"] = text
        if action == "import_data" and not str(payload.get("goal") or "").strip():
            payload["goal"] = text
        if action == "start_optimization" and has_session:
            # A live session already exists: treat new change requests as updates.
            return {"action": "apply_update", "update": text, "routed_by": "llm_coerced"}
        if action == "apply_update" and not has_session:
            return {"action": "answer", "routed_by": "llm_coerced"}
        payload["routed_by"] = "llm"
        return payload
    except Exception:  # noqa: BLE001 - any router failure falls back deterministically
        return fallback_route(text, has_session)


def fallback_summary(tool: str, payload: dict[str, Any]) -> str:
    if tool == "start_optimization":
        best = (payload.get("accepted") or {}).get("best") or {}
        solution = best.get("solution") or {}
        headline = solution.get("selected_items") or solution.get("assignments") or "committed"
        return (
            f"Optimization session started. Initial search committed a plan "
            f"(scalar={best.get('scalar')}, feasible={best.get('feasible')}, plan={_short(headline)}). "
            "Send natural-language updates in this chat to adapt it."
        )
    if tool == "apply_update":
        best = (payload.get("accepted") or {}).get("best") or {}
        restart = payload.get("restart") or {}
        loc = payload.get("localization") or {}
        mask = [
            name
            for name, flag in (("data", loc.get("data_update")), ("setup.py", loc.get("patch_setup")), ("fitness.py", loc.get("patch_fitness")))
            if flag
        ]
        return (
            f"Update applied ({', '.join(mask) if mask else 'no component'} changed). "
            f"Restart: {restart.get('restart_skill')}. "
            f"New committed plan: scalar={best.get('scalar')}, feasible={best.get('feasible')}."
        )
    return "Done."


def _short(value: Any, limit: int = 80) -> str:
    text = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
    return text if len(text) <= limit else text[: limit - 1] + "…"


def summarize_tool_result(client: Any, tool: str, payload: dict[str, Any]) -> str:
    compact = {
        "tool": tool,
        "localization": payload.get("localization"),
        "restart": {k: payload.get("restart", {}).get(k) for k in ("restart_skill", "reason")} if payload.get("restart") else None,
        "best": (payload.get("accepted") or {}).get("best"),
        "usage": payload.get("usage"),
        "latency_seconds": payload.get("latency_seconds"),
    }
    try:
        response = client.chat(
            [
                {"role": "system", "content": SUMMARIZER_SYSTEM},
                {"role": "user", "content": json.dumps(compact, ensure_ascii=False, default=str)},
            ],
            temperature=0.0,
            max_tokens=300,
        )
        text = _chat_content(response).strip()
        if text:
            return text
    except Exception:  # noqa: BLE001 - summarizer failures fall back to a template
        pass
    return fallback_summary(tool, payload)


def initial_cards(session: DemoSession, state: dict[str, Any]) -> list[dict[str, Any]]:
    accepted = state.get("accepted") or {}
    objective_names = state.get("objective_names") or []
    return [
        *result_image_cards(accepted, objective_names),
        {"type": "state", "title": "Committed plan", "data": {"best": accepted.get("best"), "objective_names": objective_names}},
        {"type": "workbench", "title": "Workbench", "data": {"changed": [], "diffs": {}, **(state.get("slots") or {})}},
        {"type": "pareto", "title": "Pareto front", "data": {"points": accepted.get("archive") or [], "objective_names": objective_names}},
    ]


def update_cards(result: dict[str, Any]) -> list[dict[str, Any]]:
    slots = result.get("slots") or {}
    accepted = result.get("accepted") or {}
    objective_names = accepted.get("objective_names") or []
    return [
        *result_image_cards(accepted, objective_names),
        {"type": "localization", "title": "Update localization", "data": result.get("localization") or {}},
        {"type": "restart", "title": "Restart decision", "data": result.get("restart") or {}},
        {"type": "state", "title": "Committed plan", "data": {"best": accepted.get("best"), "objective_names": accepted.get("objective_names") or []}},
        {
            "type": "workbench",
            "title": "Workbench diff",
            "data": {
                "changed": slots.get("changed") or [],
                "diffs": slots.get("diffs") or {},
                "setup.py": slots.get("setup_code") or "",
                "fitness.py": slots.get("fitness_code") or "",
            },
        },
        {"type": "pareto", "title": "Pareto front", "data": {"points": accepted.get("archive") or [], "objective_names": accepted.get("objective_names") or []}},
        {"type": "ledger", "title": "Event ledger", "data": {"entries": result.get("ledger") or []}},
    ]


def filter_message_for_view(message: dict[str, Any], view_mode: str) -> dict[str, Any]:
    """Normal view keeps text plus lightweight cards; professional shows all."""

    if view_mode != "normal":
        return message
    keep = {"image", "episode_preview", "error"}
    filtered = dict(message)
    filtered["cards"] = [card for card in message.get("cards") or [] if card.get("type") in keep]
    for heavy_key in ("state", "result"):
        filtered.pop(heavy_key, None)
    return filtered


def filter_messages_for_view(messages: list[dict[str, Any]], view_mode: str) -> list[dict[str, Any]]:
    return [filter_message_for_view(message, view_mode) for message in messages]


class ChatManager:
    """In-memory chat registry with JSON-file persistence."""

    def __init__(self, data_dir: Path | None = None, *, client_factory: ClientFactory | None = None):
        self.data_dir = data_dir or default_data_dir()
        self.client_factory = client_factory
        self.chats: dict[str, Chat] = {}
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._load_all()

    def _load_all(self) -> None:
        for path in sorted(self.data_dir.glob("*.json")):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                chat = Chat.from_record(record)
            except Exception:  # noqa: BLE001 - a corrupt chat file must not kill the app
                continue
            self.chats[chat.chat_id] = chat

    def _save(self, chat: Chat) -> None:
        path = self.data_dir / f"{chat.chat_id}.json"
        temporary = path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(chat.to_record(), ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(path)

    def list_chats(self) -> list[dict[str, Any]]:
        return sorted((chat.summary() for chat in self.chats.values()), key=lambda item: -item["updated_at"])

    def create_chat(self, *, title: str = "", settings: dict[str, Any] | None = None) -> Chat:
        chat = Chat(chat_id=uuid.uuid4().hex[:12], settings=merge_settings(DEFAULT_SETTINGS, settings))
        if title.strip():
            chat.title = title.strip()[:80]
        self.chats[chat.chat_id] = chat
        self._save(chat)
        return chat

    def get(self, chat_id: str) -> Chat:
        chat = self.chats.get(chat_id)
        if chat is None:
            raise KeyError(f"unknown chat: {chat_id}")
        return chat

    def delete(self, chat_id: str) -> None:
        chat = self.get(chat_id)
        self.chats.pop(chat_id, None)
        path = self.data_dir / f"{chat.chat_id}.json"
        if path.exists():
            path.unlink()

    def update_settings(self, chat_id: str, settings: dict[str, Any]) -> Chat:
        chat = self.get(chat_id)
        chat.settings = merge_settings(chat.settings, settings)
        chat._client = None  # rebuild the client with the new settings
        chat.touch()
        self._save(chat)
        return chat

    def client_for(self, chat: Chat) -> Any:
        if chat._client is None:
            from demo.session import build_client

            effective = effective_settings(chat)
            chat._client = build_client(
                provider=effective.get("provider"),
                api_key=effective.get("api_key"),
                base_url=effective.get("base_url"),
                model=effective.get("model"),
                client_factory=self.client_factory,
            )
        return chat._client

    def set_title_from(self, chat: Chat, text: str) -> None:
        if chat.title == "New chat" and text.strip():
            chat.title = text.strip()[:60]

    def handle_message(
        self,
        chat_id: str,
        text: str,
        *,
        optimization: dict[str, Any] | None = None,
        import_data: dict[str, Any] | None = None,
        upload_dir: Path | None = None,
    ) -> dict[str, Any]:
        """Run one user message through router -> tool -> summarizer."""

        chat = self.get(chat_id)
        client = self.client_for(chat)
        text = str(text or "").strip()
        if optimization:
            action = {"action": "start_optimization", "routed_by": "explicit"}
            user_content = text or f"Start optimization ({optimization.get('mode', 'builtin')})"
        elif import_data:
            action = {"action": "import_data", "routed_by": "explicit", "import_data": import_data}
            user_content = text or "Import data for optimization"
        else:
            if not text:
                raise ValueError("message text must not be empty")
            action = route_message(client, text, has_session=chat.has_live_session)
            user_content = text
        user_message = {
            "role": "user",
            "content": user_content,
            "kind": "optimization" if optimization else ("import" if import_data else "text"),
            "optimization": optimization,
            "ts": time.time(),
        }
        chat.messages.append(user_message)
        self.set_title_from(chat, user_content)

        tool = action["action"]
        if tool == "answer":
            assistant = self._answer(chat, client)
        elif tool == "start_optimization":
            assistant = self._start_optimization(chat, client, text or user_content, optimization, action, upload_dir)
        elif tool == "import_data":
            assistant = self._import_data(chat, client, action, import_data)
        else:
            assistant = self._apply_update(chat, client, action)
        assistant["routed_by"] = action.get("routed_by", "llm")
        assistant["action"] = tool
        chat.messages.append(assistant)
        chat.touch()
        self._save(chat)
        return {"message": assistant, "chat": chat.summary()}

    def _answer(self, chat: Chat, client: Any) -> dict[str, Any]:
        history = [
            {"role": str(message.get("role")), "content": str(message.get("content") or "")}
            for message in chat.messages[-HISTORY_LIMIT:]
            if message.get("role") in {"user", "assistant"}
        ]
        try:
            response = client.chat(
                [{"role": "system", "content": ASSISTANT_SYSTEM}, *history],
                temperature=0.3,
                max_tokens=1200,
            )
            content = _chat_content(response).strip()
        except Exception as exc:  # noqa: BLE001
            content = f"(assistant unavailable: {type(exc).__name__}: {exc})"
        return {"role": "assistant", "content": content or "(empty reply)", "kind": "text", "cards": [], "ts": time.time()}

    def _resolve_episode(
        self,
        chat: Chat,
        text: str,
        optimization: dict[str, Any] | None,
        action: dict[str, Any],
        upload_dir: Path | None,
    ) -> EpisodeInput:
        optimization = optimization or {}
        mode = str(optimization.get("mode") or "").strip()
        if mode == "builtin":
            return load_builtin_episode(str(optimization.get("episode_id") or ""))
        if mode == "upload":
            work_dir = upload_dir or Path(self.data_dir) / f".upload_{chat.chat_id}"
            return load_uploaded_episode(
                dict(optimization.get("episode_payload") or {}),
                dict(optimization.get("csv_files") or {}),
                work_dir,
            )
        if mode == "freeform":
            return freeform_episode(str(optimization.get("problem") or text), optimization.get("tables") or {})
        if mode == "imported":
            return load_imported_episode(optimization.get("episode_payload") or {})
        # Router-originated start: everything the user wrote is the problem.
        return freeform_episode(str(action.get("problem") or text), {})

    def _start_optimization(
        self,
        chat: Chat,
        client: Any,
        text: str,
        optimization: dict[str, Any] | None,
        action: dict[str, Any],
        upload_dir: Path | None,
    ) -> dict[str, Any]:
        episode = self._resolve_episode(chat, text, optimization, action, upload_dir)
        effective = effective_settings(chat)
        session = DemoSession.create(
            task_id=episode.episode_id,
            natural_language_problem=episode.problem,
            public_context=episode.public_context,
            provider=effective.get("provider"),
            api_key=effective.get("api_key"),
            base_url=effective.get("base_url"),
            model=effective.get("model"),
            population_size=int(effective.get("population_size") or 50),
            generations=int(effective.get("generations") or 50),
            seed=int(effective.get("seed") or 0),
            client_factory=self.client_factory,
        )
        chat.session = session
        chat.needs_reinit = False
        chat.optimization_spec = {
            "task_id": episode.episode_id,
            "problem": episode.problem,
            "public_context": _json_safe(session.public_context),
            "population_size": session.population_size,
            "generations": session.generations,
            "seed": session.seed,
        }
        state = session.state_summary()
        payload = {"accepted": state.get("accepted"), "state": state}
        summary = summarize_tool_result(client, "start_optimization", payload)
        return {
            "role": "assistant",
            "content": summary,
            "kind": "optimization_start",
            "cards": initial_cards(session, state),
            "state": state,
            "ts": time.time(),
        }

    def _import_data(
        self,
        chat: Chat,
        client: Any,
        action: dict[str, Any],
        import_data: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Convert user data into an episode and return a preview card."""

        payload = import_data or {}
        files = dict(payload.get("files") or {})
        pasted_text = str(payload.get("pasted_text") or "")
        goal = str(payload.get("goal") or action.get("goal") or "")
        if not files and not pasted_text.strip():
            # Router-originated import: the tables are inside the message text.
            pasted_text = str(action.get("goal") or "")
            goal = pasted_text
        try:
            episode = ingest_files_and_goal(client, files=files, pasted_text=pasted_text, goal=goal)
        except IngestError as exc:
            return {
                "role": "assistant",
                "content": f"I couldn't convert that data into an optimization episode: {exc}",
                "kind": "import_error",
                "cards": [{"type": "error", "title": "Import failed", "data": {"error": str(exc)}}],
                "ts": time.time(),
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "role": "assistant",
                "content": f"Data conversion failed ({type(exc).__name__}): {exc}",
                "kind": "import_error",
                "cards": [{"type": "error", "title": "Import failed", "data": {"error": f"{type(exc).__name__}: {exc}"}}],
                "ts": time.time(),
            }
        card = preview_card(episode)
        tables = card["data"]["tables"]
        summary = (
            f"I converted your data into an optimization episode '{episode.episode_id}' with "
            f"{len(tables)} table(s): " + ", ".join(f"{name} ({meta['rows']} rows)" for name, meta in tables.items()) + ". "
            "Review the preview below and confirm to start the optimization."
        )
        return {
            "role": "assistant",
            "content": summary,
            "kind": "import_preview",
            "cards": [card],
            "ts": time.time(),
        }

    def _apply_update(self, chat: Chat, client: Any, action: dict[str, Any]) -> dict[str, Any]:
        if chat.session is None:
            if chat.needs_reinit:
                return {
                    "role": "assistant",
                    "content": (
                        "This chat's optimization session was restored from disk and needs to be "
                        "re-initialized before it can accept updates. Use the re-initialize button above."
                    ),
                    "kind": "text",
                    "cards": [],
                    "ts": time.time(),
                }
            return {
                "role": "assistant",
                "content": "No optimization session is active in this chat yet. Describe an optimization problem or use the + button to start one.",
                "kind": "text",
                "cards": [],
                "ts": time.time(),
            }
        update_text = str(action.get("update") or "").strip()
        result = chat.session.apply_update(None, update_text)
        summary = summarize_tool_result(client, "apply_update", result)
        return {
            "role": "assistant",
            "content": summary,
            "kind": "optimization_update",
            "cards": update_cards(result),
            "result": result,
            "ts": time.time(),
        }

    def restart_optimization(self, chat_id: str) -> dict[str, Any]:
        """Re-initialize a restored chat's optimization session from its spec."""

        chat = self.get(chat_id)
        spec = chat.optimization_spec
        if not spec:
            raise ValueError("chat has no optimization session to re-initialize")
        effective = effective_settings(chat)
        session = DemoSession.create(
            task_id=str(spec.get("task_id") or "episode"),
            natural_language_problem=str(spec.get("problem") or ""),
            public_context=dict(spec.get("public_context") or {}),
            provider=effective.get("provider"),
            api_key=effective.get("api_key"),
            base_url=effective.get("base_url"),
            model=effective.get("model"),
            population_size=int(spec.get("population_size") or 50),
            generations=int(spec.get("generations") or 50),
            seed=int(spec.get("seed") or 0),
            client_factory=self.client_factory,
        )
        chat.session = session
        chat.needs_reinit = False
        state = session.state_summary()
        chat.messages.append(
            {
                "role": "assistant",
                "content": "Optimization session re-initialized from the saved problem. Earlier updates were not replayed; send them again if needed.",
                "kind": "optimization_start",
                "cards": initial_cards(session, state),
                "state": state,
                "ts": time.time(),
            }
        )
        chat.touch()
        self._save(chat)
        return {"message": chat.messages[-1], "chat": chat.summary()}
