"""FastAPI app for the chat-first LiveOpt demo.

Run with ``liveopt-demo`` (see ``demo.server:main``) or
``uvicorn demo.server:app``. Chats are persisted as JSON files (default
``~/.liveopt_demo/chats/``, override with ``LIVEOPT_DEMO_DATA_DIR``); API keys
stay in memory only. Blocking router/tool work runs in worker threads via
``asyncio.to_thread`` with a per-chat asyncio.Lock.

Security note: the LiveOpt pipeline executes LLM-generated Workbench code
with ``exec``. Run this demo only in trusted/local environments or containers.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from demo.chat import ChatManager, filter_message_for_view, filter_messages_for_view
from demo.episode_upload import list_builtin_episode_ids
from demo.session import ClientFactory

STATIC_DIR = Path(__file__).resolve().parent / "static"


class ChatCreateRequest(BaseModel):
    title: str = ""
    settings: dict[str, Any] = Field(default_factory=dict)


class SettingsRequest(BaseModel):
    settings: dict[str, Any] = Field(default_factory=dict)


class MessageRequest(BaseModel):
    text: str = ""
    # Explicit "Start optimization" panel payload; bypasses the router.
    optimization: dict[str, Any] | None = None
    # Explicit "Import data" panel payload: {goal, files: {name: content}, pasted_text}.
    import_data: dict[str, Any] | None = None


class ChatStore:
    """Holds the ChatManager plus per-chat async locks and busy flags."""

    def __init__(self, manager: ChatManager) -> None:
        self.manager = manager
        self.locks: dict[str, asyncio.Lock] = {}
        self.busy: dict[str, bool] = {}

    def lock_for(self, chat_id: str) -> asyncio.Lock:
        if chat_id not in self.locks:
            self.locks[chat_id] = asyncio.Lock()
        return self.locks[chat_id]


def _default_client_factory() -> ClientFactory | None:
    if os.getenv("LIVEOPT_DEMO_FAKE_CLIENT", "").strip() == "1":
        from demo.fake_client import fake_client_factory

        return fake_client_factory
    return None


def create_app(
    client_factory: ClientFactory | None = None,
    *,
    data_dir: Path | None = None,
) -> FastAPI:
    factory = client_factory if client_factory is not None else _default_client_factory()
    manager = ChatManager(data_dir, client_factory=factory)
    store = ChatStore(manager)
    app = FastAPI(title="LiveOpt Demo", version="0.2.0")
    app.state.store = store

    def get_chat_or_404(chat_id: str):
        try:
            return manager.get(chat_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @app.get("/api/episodes")
    async def list_episodes() -> dict[str, Any]:
        return {"episodes": list_builtin_episode_ids()}

    @app.get("/api/chats")
    async def list_chats() -> dict[str, Any]:
        return {"chats": manager.list_chats()}

    @app.post("/api/chats")
    async def create_chat(request: ChatCreateRequest) -> dict[str, Any]:
        chat = manager.create_chat(title=request.title, settings=request.settings)
        return {"chat": chat.summary()}

    @app.get("/api/chats/{chat_id}")
    async def get_chat(chat_id: str) -> dict[str, Any]:
        chat = get_chat_or_404(chat_id)
        view_mode = str(chat.settings.get("view_mode") or "normal")
        return {
            "chat": chat.summary(),
            "settings": {key: ("***" if key == "api_key" else value) for key, value in chat.settings.items()},
            "messages": filter_messages_for_view(chat.messages, view_mode),
        }

    @app.delete("/api/chats/{chat_id}")
    async def delete_chat(chat_id: str) -> dict[str, Any]:
        get_chat_or_404(chat_id)
        manager.delete(chat_id)
        store.busy.pop(chat_id, None)
        store.locks.pop(chat_id, None)
        return {"deleted": chat_id}

    @app.put("/api/chats/{chat_id}/settings")
    async def put_settings(chat_id: str, request: SettingsRequest) -> dict[str, Any]:
        get_chat_or_404(chat_id)
        chat = manager.update_settings(chat_id, request.settings)
        return {"chat": chat.summary()}

    @app.post("/api/chats/{chat_id}/messages")
    async def post_message(chat_id: str, request: MessageRequest) -> dict[str, Any]:
        chat = get_chat_or_404(chat_id)
        if not request.text.strip() and not request.optimization and not request.import_data:
            raise HTTPException(status_code=400, detail="message text must not be empty")
        lock = store.lock_for(chat_id)
        if lock.locked():
            raise HTTPException(status_code=409, detail="chat is busy processing another message")
        async with lock:
            store.busy[chat_id] = True
            started = time.perf_counter()
            try:
                result = await asyncio.to_thread(
                    manager.handle_message,
                    chat_id,
                    request.text,
                    optimization=request.optimization,
                    import_data=request.import_data,
                )
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=500, detail=f"message failed: {type(exc).__name__}: {exc}"
                ) from exc
            finally:
                store.busy[chat_id] = False
        view_mode = str(chat.settings.get("view_mode") or "normal")
        result["message"] = filter_message_for_view(result["message"], view_mode)
        result["latency_seconds"] = time.perf_counter() - started
        return result

    @app.get("/api/chats/{chat_id}/status")
    async def chat_status(chat_id: str) -> dict[str, Any]:
        chat = get_chat_or_404(chat_id)
        return {
            "chat_id": chat_id,
            "busy": bool(store.busy.get(chat_id)),
            "message_count": len(chat.messages),
            "has_optimization": chat.optimization_spec is not None,
            "needs_reinit": chat.needs_reinit,
        }

    @app.post("/api/chats/{chat_id}/optimization/restart")
    async def restart_optimization(chat_id: str) -> dict[str, Any]:
        chat = get_chat_or_404(chat_id)
        lock = store.lock_for(chat_id)
        async with lock:
            store.busy[chat_id] = True
            try:
                result = await asyncio.to_thread(manager.restart_optimization, chat_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            except Exception as exc:  # noqa: BLE001
                raise HTTPException(
                    status_code=500, detail=f"re-initialization failed: {type(exc).__name__}: {exc}"
                ) from exc
            finally:
                store.busy[chat_id] = False
        view_mode = str(chat.settings.get("view_mode") or "normal")
        result["message"] = filter_message_for_view(result["message"], view_mode)
        return result

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
    return app


app = create_app()


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the LiveOpt chat demo.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="enable uvicorn auto-reload")
    args = parser.parse_args()
    import uvicorn

    if args.reload:
        uvicorn.run("demo.server:app", host=args.host, port=args.port, reload=True)
    else:
        uvicorn.run(create_app(), host=args.host, port=args.port)


if __name__ == "__main__":
    main()
