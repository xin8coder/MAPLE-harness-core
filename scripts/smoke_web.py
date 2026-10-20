#!/usr/bin/env python3
"""Boot a fresh DSH web profile and verify the installed application without an LLM."""
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import tempfile
import time
from urllib.error import HTTPError
from urllib.request import build_opener, HTTPCookieProcessor, ProxyHandler, Request
from launcher import application_home, node_paths, terminate


def main():
    root = Path(__file__).resolve().parents[1]
    home = application_home()
    _, node, _ = node_paths(home)
    dsh = [str(node), str(home / 'dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js')]
    with tempfile.TemporaryDirectory(prefix='maple-web-smoke-') as temp:
        temp = Path(temp)
        env = os.environ.copy()
        for name in ('DEEPSEEK_API_KEY', 'KIMI_API_KEY', 'LIVEOPT_ENV_FILE', 'LIVEOPT_DSH_PUBLIC_URL'):
            env.pop(name, None)
        env.update(MAPLE_HOME=str(home), DSH_HOME=str(temp / 'dsh-home'),
                   LIVEOPT_MCP_STATE_DIR=str(temp / 'state'), LIVEOPT_MCP_WORKSPACE_ROOT=str(temp / 'workspace'))
        (temp / 'workspace').mkdir()
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        env['MAPLE_PORT'] = str(port)
        subprocess.run([*dsh, 'plugin', '--profile', 'web', 'add', str(root / 'dsh-bundle')],
                       env=env, cwd=temp / 'workspace', check=True, stdout=subprocess.DEVNULL)
        log_path = temp / 'startup.log'
        with log_path.open('w') as log:
            options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen([sys.executable, str(root / 'scripts/launcher.py'), '--no-browser'], env=env, cwd=root, stdout=log,
                                       stderr=subprocess.STDOUT, **options)
        try:
            launch = None
            for _ in range(1800):
                match = re.search(rf'http://127\.0\.0\.1:{port}/\?token=\S+', log_path.read_text())
                if match:
                    launch = match.group(0)
                    break
                if process.poll() is not None:
                    raise RuntimeError('DSH failed to boot; inspect the private test startup log')
                time.sleep(0.1)
            if not launch:
                raise TimeoutError('DSH did not publish a launch link within 180 seconds')
            base = f'http://127.0.0.1:{port}'
            opener = build_opener(ProxyHandler({}), HTTPCookieProcessor(CookieJar()))
            try:
                opener.open(base + '/liveopt-api/health')
                raise AssertionError('application API was reachable without pairing')
            except HTTPError as error:
                assert error.code == 401
            assert b'<title>MAPLE Harness</title>' in opener.open(launch).read()
            for route in ['/health', '/settings', '/brand/maple-logo.png', '/explorer/', '/explorer/explorer.js', '/explorer/echarts.min.js']:
                with opener.open(base + '/liveopt-api' + route) as response:
                    assert response.status == 200
                    assert len(response.read()) > 0
            try:
                opener.open(Request(base + '/liveopt-api/settings', headers={'Origin': 'https://untrusted.invalid'}))
                raise AssertionError('cross-origin access was accepted')
            except HTTPError as error:
                assert error.code == 403
            upload = Request(base + '/liveopt-api/uploads?filename=orders.csv', data='名称,数量\n外贸订单,20\n'.encode(),
                             headers={'Content-Type': 'text/csv'}, method='POST')
            data = json.loads(opener.open(upload).read())
            assert data['upload_id']
            print('Fresh web profile: pairing, origin checks, settings, upload, and installed explorer assets passed.')
        finally:
            terminate(process)


if __name__ == '__main__':
    main()
