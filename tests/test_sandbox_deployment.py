from __future__ import annotations

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('sandbox_setup', ROOT/'deploy/sandbox/setup.py')
setup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(setup)


def values(tmp_path):
    return {'MAPLE_HOME': str(tmp_path/'runtime-home'), 'MAPLE_CADDY': str(tmp_path/'caddy'),
        'MAPLE_BIND': '127.0.0.1', 'MAPLE_PORT': 13000, 'MAPLE_GATEWAY_PORT': 18960,
        'MAPLE_AUTH_PORT': 18961, 'MAPLE_MODEL_PORT': 18080, 'MAPLE_WEB_PORT': 3101,
        'MAPLE_API_PORT': 3102, 'MAPLE_TUNNEL': 'none', 'MAPLE_CLOUDFLARED': 'cloudflared',
        'MAPLE_PUBLIC_ORIGIN': '', 'MAPLE_SERVICE_PREFIX': 'maple-sandbox-test'}


@pytest.mark.parametrize('key,value', [('MAPLE_BIND', '0.0.0.0'), ('MAPLE_BIND', '8.8.8.8'),
    ('MAPLE_PORT', 3101), ('MAPLE_PORT', 80), ('MAPLE_SERVICE_PREFIX', 'name\nExecStart=bad'),
    ('MAPLE_PUBLIC_ORIGIN', 'https://example.com/path'),
    ('MAPLE_PUBLIC_ORIGIN', 'https://user:password@example.com'),
    ('MAPLE_PUBLIC_ORIGIN', "https://example.com'"),
    ('MAPLE_PUBLIC_ORIGIN', 'https://example.com:invalid')])
def test_invalid_deployment_settings_are_rejected(tmp_path, key, value):
    with pytest.raises(ValueError):
        setup.validate_values({**values(tmp_path), key: value})


def test_named_tunnel_requires_a_public_origin(tmp_path):
    with pytest.raises(ValueError, match='public-origin'):
        setup.validate_values({**values(tmp_path), 'MAPLE_TUNNEL': 'named'})


@pytest.mark.skipif(sys.platform != 'linux', reason='The isolated server is Linux-only')
def test_credentials_stay_outside_sandbox_and_updates_preserve_them(tmp_path):
    # A short path keeps Linux's Unix-socket length bound independent of pytest's base.
    import tempfile
    with tempfile.TemporaryDirectory(prefix='maple-unit-') as directory:
        root = Path(directory)/'server'
        key, password = 'local-provider-mock', 'local-login-test'
        config = setup.prepare(root, values(tmp_path), api_key=key, password=password)
        assert (root/'secrets/front.env').stat().st_mode & 0o777 == 0o600
        assert (root/'secrets/llm.env').stat().st_mode & 0o777 == 0o600
        assert root.stat().st_mode & 0o777 == 0o700
        assert key not in (root/'data/dsh-home/.credentials.yaml').read_text()
        auth = dict(line.split('=', 1) for line in (root/'secrets/front.env').read_text().splitlines())
        assert password not in json.dumps(auth)
        assert hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(auth['MAPLE_FRONT_SALT']), 200_000).hex() == auth['MAPLE_FRONT_PBKDF2']
        files = [root/'secrets/front.env', root/'secrets/llm.env', root/'data/dsh-home/.credentials.yaml']
        before = {path: path.read_bytes() for path in files}
        setup.install_assets(root)
        assert all(path.read_bytes() == data for path, data in before.items())
        assert key not in json.dumps(config)
        units = setup.unit_texts(root, config)
        assert all(key not in content and password not in content for content in units.values())
        assert 'maple-sandbox-test-tunnel.service' not in units
        assert 'BindsTo=maple-sandbox-test-sandbox.service' in units['maple-sandbox-test-front.service']
        with pytest.raises(FileExistsError):
            setup.prepare(root, values(tmp_path), api_key=key, password='not-used')


def test_shell_configuration_is_quoted_not_interpolated(tmp_path):
    target = tmp_path/'config.env'
    text = 'value with spaces; $(not-a-command)'
    setup.write_env(target, {'EXAMPLE': text})
    assert shlex.split(target.read_text())[0] == 'EXAMPLE='+text


def test_runtime_does_not_mount_host_credentials_or_model_secret():
    source = (ROOT/'deploy/sandbox/sandbox.sh').read_text()
    assert '--unshare-all' in source and '--cap-drop ALL' in source
    assert '--bind "$D" /data' in source
    assert 'secrets/llm.env' not in source
    assert 'dsh-home/.credentials.yaml' not in source
    assert '--share-net' not in source
    assert 'sk-sandbox-placeholder' in source


def test_gateway_requires_runtime_credentials():
    source = (ROOT/'deploy/sandbox/auth.py').read_text()
    assert 'os.environ["MAPLE_FRONT_PBKDF2"]' in source
    assert 'os.environ["MAPLE_SESSION_SECRET"]' in source


def test_new_instance_cannot_overwrite_another_instances_services(tmp_path):
    path = tmp_path/'maple-sandbox-test-auth.service'
    path.write_text('ExecStart=/bin/bash /other-instance/app/start-auth.sh\n')
    config = values(tmp_path)
    with pytest.raises(ValueError, match='another installation'):
        setup.validate_unit_ownership(tmp_path, tmp_path/'server', setup.unit_texts(tmp_path/'server', config))
    assert '/other-instance/' in path.read_text()


def test_login_return_path_cannot_escape_the_current_site(monkeypatch):
    monkeypatch.setenv('MAPLE_FRONT_USER', 'example')
    monkeypatch.setenv('MAPLE_FRONT_SALT', bytes(24).hex())
    monkeypatch.setenv('MAPLE_FRONT_PBKDF2', bytes(32).hex())
    monkeypatch.setenv('MAPLE_SESSION_SECRET', bytes(32).hex())
    spec = importlib.util.spec_from_file_location('sandbox_auth_test', ROOT/'deploy/sandbox/auth.py')
    auth = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(auth)
    for path in ['//outside.invalid', '/\\outside.invalid', '/\r\nX-Injected: bad']:
        assert auth.safe_next(path) == '/'
    assert auth.safe_next('/?view=solutions') == '/?view=solutions'


@pytest.mark.skipif(sys.platform != 'linux', reason='The isolated server is Linux-only')
@pytest.mark.parametrize('message,child_exit,expected', [
    ('Unauthorized: Tunnel not found', None, 1),
    ('connection reset by peer; retrying', 0, 0),
    ('failed to start tunnel', 7, 7),
])
def test_quick_tunnel_recycles_deleted_registration_and_reaps_child(tmp_path, message, child_exit, expected):
    root = tmp_path/'server'
    app = root/'app'
    app.mkdir(parents=True)
    runtime = tmp_path/'runtime'
    (runtime/'bin').mkdir(parents=True)
    systemctl = runtime/'bin/systemctl'
    systemctl.write_text('#!/bin/sh\nexit 0\n')
    systemctl.chmod(0o755)
    for name in ['common.sh', 'start-tunnel.sh']:
        shutil.copyfile(ROOT/'deploy/sandbox'/name, app/name)
    child = tmp_path/'mock-cloudflared'
    child.write_text('#!/bin/sh\n'
        'printf "%s" "$$" > "$MAPLE_TEST_CHILD_PID"\n'
        'echo "https://mock-recovery.trycloudflare.com"\n'
        f'echo {shlex.quote(message)}\n'
        + ('exec sleep 60\n' if child_exit is None else f'exit {child_exit}\n'))
    child.chmod(0o755)
    setup.write_env(root/'config.env', {
        **values(tmp_path), 'MAPLE_HOME': str(runtime),
        'MAPLE_TUNNEL': 'quick', 'MAPLE_CLOUDFLARED': str(child),
    })
    pid_file = tmp_path/'child.pid'
    result = subprocess.run(['bash', str(app/'start-tunnel.sh')],
        env={**os.environ, 'MAPLE_TEST_CHILD_PID': str(pid_file)},
        capture_output=True, text=True, timeout=10)
    assert result.returncode == expected, result.stderr
    assert (root/'public-url.txt').read_text().strip() == 'https://mock-recovery.trycloudflare.com'
    with pytest.raises(ProcessLookupError):
        os.kill(int(pid_file.read_text()), 0)
    assert ('requesting a new public URL' in result.stderr) == (child_exit is None)
