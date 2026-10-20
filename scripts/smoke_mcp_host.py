#!/usr/bin/env python3
"""Verify the real DSH/MCP boundary with a local provider on Windows or Linux."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time

from launcher import application_home, environment, node_paths, terminate


def main():
    root = Path(__file__).resolve().parents[1]
    home = application_home()
    _, node, _ = node_paths(home)
    dsh = [str(node), str(home / 'dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js')]
    scripts = home / 'runtime/venv' / ('Scripts' if os.name == 'nt' else 'bin')
    with tempfile.TemporaryDirectory(prefix='maple-host-smoke-') as temp:
        temp = Path(temp)
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env = environment(home, node)
        env.update(DSH_HOME=str(temp / 'dsh-home'), DEEPSEEK_API_KEY='mock-only',
                   DEEPSEEK_BASE_URL=f'http://127.0.0.1:{port}/v1',
                   LIVEOPT_MCP_COMMAND=str(scripts / ('liveopt-mcp.exe' if os.name == 'nt' else 'liveopt-mcp')),
                   LIVEOPT_MCP_STATE_DIR=str(temp / 'state'), LIVEOPT_MCP_WORKSPACE_ROOT=str(temp))
        subprocess.run([*dsh, 'plugin', '--profile', 'headless', 'add', str(root / 'dsh-bundle')], env=env, cwd=temp, check=True, stdout=subprocess.DEVNULL)
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        mock = subprocess.Popen([sys.executable, str(root / 'tests/mock_dsh_llm.py'), '--port', str(port), '--requests', str(temp / 'requests.jsonl')], **options)
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1', port), timeout=0.1):
                        break
                except OSError:
                    time.sleep(0.1)
            result = subprocess.run([*dsh, '--profile', 'headless', 'Exercise one LiveOpt MCP tool.'], env=env, cwd=temp,
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, encoding='utf-8', timeout=90)
            if result.returncode:
                raise RuntimeError(result.stderr)
            rows = [json.loads(line) for line in (temp / 'requests.jsonl').read_text().splitlines()]
            assert any('mcp__liveopt__liveopt_cancel' in row['tools'] for row in rows)
            assert any(row['liveopt_skill_visible'] for row in rows)
            assert 'LiveOpt MCP tool-call path completed' in result.stdout
            print('Official DSH -> MAPLE MCP call passed with the local provider mock.')
        finally:
            terminate(mock)


if __name__ == '__main__':
    main()
