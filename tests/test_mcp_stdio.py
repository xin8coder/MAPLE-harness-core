from __future__ import annotations

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


def test_stdio_server_advertises_only_compact_liveopt_protocol(tmp_path):
    async def run() -> None:
        env = dict(os.environ)
        env["LIVEOPT_MCP_STATE_DIR"] = str(tmp_path / "state")
        env["LIVEOPT_MCP_WORKSPACE_ROOT"] = str(tmp_path)
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "liveopt_dsh.mcp_server", "--transport", "stdio"],
            env=env,
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                listed = await session.list_tools()
                tools = {tool.name: tool for tool in listed.tools}
                assert set(tools) == {
                    "liveopt_prepare_data",
                    "liveopt_prepare_uploads",
                    "liveopt_start",
                    "liveopt_update",
                    "liveopt_override_slots",
                    "liveopt_wait",
                    "liveopt_inspect",
                    "liveopt_export",
                    "liveopt_cancel",
                }
                assert "problem" in tools["liveopt_start"].input_schema["properties"]
                assert "solver_preference" in tools["liveopt_start"].input_schema["properties"]
                assert "prepared_data_id" in tools["liveopt_start"].input_schema["properties"]
                assert "provider" not in tools["liveopt_start"].input_schema["properties"]
                assert "model" not in tools["liveopt_start"].input_schema["properties"]
                assert tools["liveopt_start"].input_schema["required"] == ["problem"]
                assert set(tools["liveopt_update"].input_schema["required"]) == {
                    "session_id",
                    "update",
                }
                assert tools["liveopt_override_slots"].input_schema["required"] == [
                    "session_id"
                ]
                prepare_properties = tools["liveopt_prepare_data"].input_schema[
                    "properties"
                ]
                assert {"sources", "inline_tables", "column_groups"} <= set(
                    prepare_properties
                )
                upload_properties = tools["liveopt_prepare_uploads"].input_schema[
                    "properties"
                ]
                assert {"upload_ids", "inline_tables", "column_groups"} <= set(
                    upload_properties
                )
                assert tools["liveopt_prepare_uploads"].input_schema["required"] == [
                    "upload_ids"
                ]

    asyncio.run(run())
