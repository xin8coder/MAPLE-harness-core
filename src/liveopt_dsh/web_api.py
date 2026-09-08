"""Browser surface for uploads, progress, and artifact downloads."""

from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from .app_settings import (
    credential_status,
    load_application_settings,
    save_application_settings,
    save_deepseek_api_key,
)
from .documents import SUPPORTED_UPLOAD_SUFFIXES, TABULAR_SUFFIXES
from .exports import export_session
from .solutions import list_solution_sessions, solution_timeline
from .store import StateStore


_JOB_PATH = re.compile(r"^/jobs/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})$")
_ARTIFACT_PATH = re.compile(r"^/artifacts/(.+)$")
_RESULT_PATH = re.compile(r"^/results/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})$")
_SOLUTION_PATH = re.compile(
    r"^/solution-sessions/([A-Za-z0-9][A-Za-z0-9_.-]{0,127})$"
)
_BRAND_PATH = re.compile(r"^/brand/((?:liveopt-mark-(?:64|256|512)|maple-logo)\.png)$")
_BRAND_DIR = Path(__file__).resolve().parent / "assets"


def make_handler(
    store: StateStore,
    *,
    max_upload_bytes: int | None = None,
) -> type[BaseHTTPRequestHandler]:
    upload_limit = int(
        max_upload_bytes
        if max_upload_bytes is not None
        else os.getenv("LIVEOPT_MCP_MAX_UPLOAD_BYTES", str(25 * 1024 * 1024))
    )

    class LiveOptWebHandler(BaseHTTPRequestHandler):
        server_version = "LiveOptProgress/1.0"

        def do_GET(self) -> None:  # noqa: N802 - stdlib handler contract
            request_url = urlsplit(self.path)
            path = request_url.path
            query = parse_qs(request_url.query)
            if path == "/health":
                self._json({"status": "ok"})
                return
            if path == "/settings":
                self._json(
                    {
                        **load_application_settings(store.root),
                        "api": credential_status(),
                        "provider": "DeepSeek",
                        "model": "deepseek-v4-flash",
                        "endpoint": "https://api.deepseek.com/v1",
                        "theme": "light",
                    }
                )
                return
            if path == "/solution-sessions":
                self._json({"sessions": list_solution_sessions(store)})
                return
            match = _SOLUTION_PATH.fullmatch(path)
            if match:
                try:
                    payload = solution_timeline(store, match.group(1))
                except KeyError:
                    self._json({"error": "session not found"}, status=404)
                    return
                self._json(payload)
                return
            match = _BRAND_PATH.fullmatch(path)
            if match:
                asset = _BRAND_DIR / match.group(1)
                if not asset.is_file():
                    self._json({"error": "brand asset not found"}, status=404)
                    return
                payload = asset.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "image/png")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Cache-Control", "public, max-age=86400")
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)
                return
            match = _JOB_PATH.fullmatch(path)
            if match:
                try:
                    payload = store.load_job(match.group(1))
                except KeyError:
                    self._json({"error": "job not found"}, status=404)
                    return
                started = payload.get("started_at") or payload.get("created_at") or time.time()
                stopped = payload.get("finished_at") or time.time()
                payload["elapsed_seconds"] = round(
                    max(0.0, float(stopped) - float(started)), 3
                )
                self._json(payload)
                return
            match = _RESULT_PATH.fullmatch(path)
            if match:
                session_id = match.group(1)
                try:
                    snapshot = store.load_snapshot(session_id)
                    requested_turn = query.get("turn", [None])[0]
                    turn = (
                        int(requested_turn)
                        if requested_turn is not None
                        else int(snapshot.get("turn") or 0)
                    )
                    artifact = store.resolve_artifact(
                        f"sessions/{session_id}/exports/t{turn:03d}/ui_result.json"
                    )
                    payload = json.loads(artifact.read_text(encoding="utf-8"))
                except FileNotFoundError:
                    try:
                        payload = export_session(store, session_id)
                    except KeyError:
                        self._json({"error": "session not found"}, status=404)
                        return
                except KeyError:
                    self._json({"error": "session not found"}, status=404)
                    return
                self._json(payload)
                return
            match = _ARTIFACT_PATH.fullmatch(path)
            if match:
                try:
                    artifact = store.resolve_artifact(unquote(match.group(1)))
                except (FileNotFoundError, ValueError):
                    self._json({"error": "artifact not found"}, status=404)
                    return
                content_type = mimetypes.guess_type(artifact.name)[0] or "application/octet-stream"
                payload = artifact.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.send_header(
                    "Content-Disposition", f'attachment; filename="{artifact.name}"'
                )
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)
                return
            self._json({"error": "not found"}, status=404)

        def do_POST(self) -> None:  # noqa: N802 - stdlib handler contract
            parsed = urlsplit(self.path)
            if parsed.path == "/settings":
                try:
                    content_length = int(self.headers.get("Content-Length") or "0")
                except ValueError:
                    content_length = 0
                if content_length <= 0 or content_length > 64 * 1024:
                    self._json({"error": "invalid settings request"}, status=400)
                    return
                try:
                    payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
                except (UnicodeDecodeError, ValueError):
                    self._json({"error": "settings body must be a JSON object"}, status=400)
                    return
                if not isinstance(payload, dict):
                    self._json({"error": "settings body must be a JSON object"}, status=400)
                    return
                try:
                    current = load_application_settings(store.root)
                    generations = payload.get("generations", current["generations"])
                    settings = save_application_settings(
                        store.root,
                        generations=generations,
                    )
                    if payload.get("api_key") is not None:
                        save_deepseek_api_key(str(payload["api_key"]))
                except ValueError as exc:
                    self._json({"error": str(exc)}, status=400)
                    return
                self._json(
                    {
                        **settings,
                        "api": credential_status(),
                        "provider": "DeepSeek",
                        "model": "deepseek-v4-flash",
                        "endpoint": "https://api.deepseek.com/v1",
                        "theme": "light",
                    }
                )
                return
            if parsed.path != "/uploads":
                self._json({"error": "not found"}, status=404)
                return
            filename = (parse_qs(parsed.query).get("filename") or [""])[0].strip()
            suffix = Path(filename).suffix.lower()
            if suffix not in SUPPORTED_UPLOAD_SUFFIXES:
                self._json(
                    {
                        "error": "unsupported document type",
                        "supported_extensions": sorted(SUPPORTED_UPLOAD_SUFFIXES),
                    },
                    status=415,
                )
                return
            try:
                content_length = int(self.headers.get("Content-Length") or "0")
            except ValueError:
                content_length = 0
            if content_length <= 0:
                self._json({"error": "uploaded document is empty"}, status=400)
                return
            if content_length > upload_limit:
                self._json(
                    {"error": "uploaded document exceeds the size limit", "limit_bytes": upload_limit},
                    status=413,
                )
                return
            payload = self.rfile.read(content_length)
            if len(payload) != content_length:
                self._json({"error": "incomplete upload body"}, status=400)
                return
            media_type = (self.headers.get("Content-Type") or "application/octet-stream").split(";", 1)[0]
            try:
                metadata = store.save_upload(
                    filename=filename,
                    media_type=media_type,
                    payload=payload,
                )
            except ValueError as exc:
                self._json({"error": str(exc)}, status=400)
                return
            self._json(
                {
                    "upload_id": metadata["upload_id"],
                    "filename": metadata["filename"],
                    "media_type": metadata["media_type"],
                    "size_bytes": metadata["size_bytes"],
                    "sha256": metadata["sha256"],
                    "kind": "tables" if suffix in TABULAR_SUFFIXES else "document",
                },
                status=201,
            )

        def do_OPTIONS(self) -> None:  # noqa: N802 - stdlib handler contract
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

        def _json(self, payload: dict[str, object], *, status: int = 200) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.end_headers()
            self.wfile.write(encoded)

    return LiveOptWebHandler


def main() -> None:
    parser = argparse.ArgumentParser(description="LiveOpt browser progress API")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8766)
    args = parser.parse_args()
    state_dir = Path(
        os.getenv("LIVEOPT_MCP_STATE_DIR", "~/.local/share/liveopt-dsh/state")
    ).expanduser()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(StateStore(state_dir)))
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
