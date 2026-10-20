from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('maple_launcher', ROOT / 'scripts/launcher.py')
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)


def test_bootstrap_entrypoints_are_pinned_consistently():
    pins = json.loads((ROOT / 'runtime/bootstrap.json').read_text())
    shell = (ROOT / 'start.sh').read_text()
    assert pins['uv_version'] in shell
    assert pins['python_version'] in shell
    for filename, checksum in pins['uv_sha256'].items():
        if 'linux' in filename:
            assert checksum in shell
    windows = (ROOT / 'scripts/start_windows.ps1').read_text()
    assert 'Get-FileHash' in windows
    assert 'uv.exe' in windows
    assert 'python install' in windows
    assert 'launcher.py' in windows
    assert 'ExecutionPolicy Bypass' in (ROOT / 'start.cmd').read_text()


def test_launcher_uses_separate_state_and_detects_current_platform(tmp_path, monkeypatch):
    monkeypatch.setenv('MAPLE_HOME', str(tmp_path / 'maple home'))
    assert launcher.application_home() == (tmp_path / 'maple home').resolve()
    _, node, corepack = launcher.node_paths(tmp_path)
    assert node.name == ('node.exe' if os.name == 'nt' else 'node')
    assert corepack.name == 'corepack.js'
    env = launcher.environment(tmp_path, node)
    assert Path(env['LIVEOPT_MCP_STATE_DIR']).is_dir()
    assert Path(env['LIVEOPT_MCP_WORKSPACE_ROOT']).is_dir()


def test_busy_web_port_uses_another_port():
    import socket
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        busy = sock.getsockname()[1]
        assert launcher.free_port(busy) != busy


def test_windows_credentials_do_not_require_fchmod(tmp_path, monkeypatch):
    from liveopt_dsh import app_settings
    monkeypatch.delattr(app_settings.os, 'fchmod', raising=False)
    path = tmp_path / 'settings.json'
    app_settings._atomic_text(path, '{}', mode=0o600)
    assert path.read_text() == '{}'
