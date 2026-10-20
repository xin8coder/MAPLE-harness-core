"""Tiny SSE model used only by the DSH bundle smoke test."""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def _chunk(content: dict, finish_reason=None, *, usage=False) -> dict:
    payload = {
        "id": "liveopt-smoke",
        "object": "chat.completion.chunk",
        "created": 0,
        "model": "deepseek-chat",
        "choices": [{"index": 0, "delta": content, "finish_reason": finish_reason}],
    }
    if usage:
        payload["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    return payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--requests", type=Path, required=True)
    args = parser.parse_args()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802 - stdlib HTTP API
            body = json.loads(
                self.rfile.read(int(self.headers.get("content-length", "0"))) or b"{}"
            )
            tools = [
                item.get("name") or item.get("function", {}).get("name")
                for item in body.get("tools", [])
            ]
            roles = [item.get("role") for item in body.get("messages", [])]
            message_text = str(body.get("system", "")) + "\n" + "\n".join(
                str(item.get("content") or "") for item in body.get("messages", [])
            )
            with args.requests.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(
                        {
                            "roles": roles,
                            "tools": tools,
                            "liveopt_skill_visible": (
                                "<available_skills>" in message_text
                                and "liveopt" in message_text.lower()
                            ),
                        }
                    )
                    + "\n"
                )
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if self.path.rstrip("/").endswith("/messages"):
                tool_returned = any(
                    isinstance(item.get("content"), list)
                    and any(block.get("type") == "tool_result" for block in item["content"])
                    for item in body.get("messages", [])
                )
                call_tool = "mcp__liveopt__liveopt_cancel" in tools and not tool_returned
                block = (
                    {"type": "tool_use", "id": "call_liveopt", "name": "mcp__liveopt__liveopt_cancel", "input": {"job_id": "missing-smoke-job"}}
                    if call_tool else
                    {"type": "text", "text": "LiveOpt MCP tool-call path completed."}
                )
                events = [
                    {"type": "message_start", "message": {"id": "maple-smoke", "model": "deepseek-flash", "usage": {"input_tokens": 1, "output_tokens": 0}}},
                    {"type": "content_block_start", "index": 0, "content_block": block},
                    {"type": "content_block_stop", "index": 0},
                    {"type": "message_delta", "delta": {"stop_reason": "tool_use" if call_tool else "end_turn"}, "usage": {"output_tokens": 1}},
                    {"type": "message_stop"},
                ]
                for event in events:
                    self.wfile.write(("data: " + json.dumps(event) + "\n\n").encode())
                self.wfile.flush()
                return
            if "tool" in roles:
                chunks = [
                    _chunk({"role": "assistant", "content": "LiveOpt MCP tool-call path completed."}),
                    _chunk({}, "stop", usage=True),
                ]
            elif "mcp__liveopt__liveopt_cancel" in tools:
                chunks = [
                    _chunk(
                        {
                            "role": "assistant",
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call_liveopt",
                                    "type": "function",
                                    "function": {
                                        "name": "mcp__liveopt__liveopt_cancel",
                                        "arguments": '{"job_id":"missing-smoke-job"}',
                                    },
                                }
                            ],
                        }
                    ),
                    _chunk({}, "tool_calls", usage=True),
                ]
            else:
                chunks = [
                    _chunk({"role": "assistant", "content": "LiveOpt smoke"}),
                    _chunk({}, "stop", usage=True),
                ]
            for chunk in chunks:
                self.wfile.write(("data: " + json.dumps(chunk) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")
            self.wfile.flush()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    ThreadingHTTPServer(("127.0.0.1", args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
