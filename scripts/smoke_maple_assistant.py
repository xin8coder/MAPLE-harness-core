#!/usr/bin/env python3
"""Exercise the actual web preset and MCP tools using only a local model mock."""
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
import uuid

from launcher import application_home, environment, node_paths, terminate


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def main():
    root = Path(__file__).resolve().parents[1]
    home = application_home()
    _, node, _ = node_paths(home)
    dsh = [str(node), str(home / 'dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js')]
    with tempfile.TemporaryDirectory(prefix='maple-persona-smoke-') as directory:
        temp = Path(directory)
        env = environment(home, node)
        for name in ('KIMI_API_KEY', 'LIVEOPT_ENV_FILE', 'HTTP_PROXY', 'HTTPS_PROXY',
                     'ALL_PROXY', 'http_proxy', 'https_proxy', 'all_proxy'):
            env.pop(name, None)
        web_port, model_port = free_port(), free_port()
        scripts = home / 'runtime/venv' / ('Scripts' if os.name == 'nt' else 'bin')
        env.update(DSH_HOME=str(temp / 'dsh-home'), DEEPSEEK_API_KEY='mock-only',
                   DEEPSEEK_BASE_URL=f'http://127.0.0.1:{model_port}', NODE_USE_ENV_PROXY='0',
                   LIVEOPT_MCP_COMMAND=str(scripts / ('liveopt-mcp.exe' if os.name == 'nt' else 'liveopt-mcp')),
                   LIVEOPT_MCP_STATE_DIR=str(temp / 'state'), LIVEOPT_MCP_WORKSPACE_ROOT=str(temp))
        subprocess.run([*dsh, 'plugin', '--profile', 'web', 'add', str(root / 'dsh-bundle')],
                       env=env, cwd=temp, check=True, stdout=subprocess.DEVNULL)
        options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
        mock = subprocess.Popen([sys.executable, str(root / 'tests/mock_dsh_llm.py'),
                                 '--port', str(model_port), '--requests', str(temp / 'requests.jsonl')], **options)
        process = None
        try:
            for _ in range(100):
                try:
                    with socket.create_connection(('127.0.0.1', model_port), timeout=.1):
                        break
                except OSError:
                    time.sleep(.1)
            log_path = temp / 'host.log'
            with log_path.open('w') as log:
                process = subprocess.Popen([*dsh, '--profile', 'web', '--host', '127.0.0.1',
                                            '--port', str(web_port), '--no-open'], env=env, cwd=temp,
                                           stdout=log, stderr=subprocess.STDOUT, **options)
            deadline = time.monotonic() + 120
            launch = None
            while time.monotonic() < deadline:
                match = re.search(rf'http://127\.0\.0\.1:{web_port}/\?token=\S+', log_path.read_text())
                if match:
                    launch = match.group(0)
                    break
                if process.poll() is not None:
                    # The disposable test log contains no real credentials.
                    detail = re.sub(r'token=\S+', 'token=[redacted]', log_path.read_text())
                    raise RuntimeError(detail)
                time.sleep(.1)
            if not launch:
                raise TimeoutError('The test web host did not become ready')
            opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
            opener.open(launch, timeout=15).close()
            base = f'http://127.0.0.1:{web_port}'

            def rpc(method, request):
                body = {'type': 'client-request', 'rpcId': str(uuid.uuid4()),
                        'method': method, 'payload': {'args': {'request': request}}}
                response = json.loads(opener.open(Request(base + '/api/' + method,
                    data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'}), timeout=30).read())['result']
                if not response.get('ok'):
                    raise RuntimeError(str(response.get('error')))
                return response['value']

            session_id = rpc('session/create', {'cwd': str(temp)})['sessionId']
            rpc('session/prompt', {'sessionId': session_id, 'requestId': str(uuid.uuid4()),
                'mode': 'queue', 'content': [{'type': 'text', 'text': '测试 MAPLE 工具通路。'}]})
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                projection = rpc('session/projections', {'sessionId': session_id})
                page = rpc('session/page', {'address': {'kind': 'session', 'sessionId': session_id},
                    'throughSeq': projection['asOfSeq'], 'maxMessages': 10})
                record_file = temp / 'requests.jsonl'
                rows = [json.loads(line) for line in record_file.read_text().splitlines()] if record_file.exists() else []
                agent_rows = [row for row in rows if 'mcp__liveopt__liveopt_cancel' in row['tools']]
                messages = [row for row in page.get('records', [])
                            if row.get('event', {}).get('type') == 'assistant/message']
                if len(agent_rows) >= 2 and 'LiveOpt MCP tool-call path completed' in json.dumps(messages):
                    break
                time.sleep(.25)
            else:
                raise TimeoutError('The mock did not complete the MCP round trip')
            rows = [json.loads(line) for line in (temp / 'requests.jsonl').read_text().splitlines()]
            agent_rows = [row for row in rows if 'mcp__liveopt__liveopt_cancel' in row['tools']]
            assert len(agent_rows) >= 2, rows
            for row in agent_rows:
                assert row['maple_persona_visible'], row
                assert row['maple_workflow_visible'], row
                assert not row['coding_persona_visible'], row
                assert set(row['tools']) <= {
                    'skill', 'ask_user_question',
                    *[tool for tool in row['tools'] if tool.startswith('mcp__liveopt__')],
                }, row['tools']
            print('Official web preset: lanchou identity, MAPLE algorithm, no coding tools, and MCP round trip passed (no real API).')
        finally:
            if process is not None:
                terminate(process)
            terminate(mock)


if __name__ == '__main__':
    main()
