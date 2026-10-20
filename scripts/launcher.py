#!/usr/bin/env python3
"""Native Windows/Linux installation and browser launch, without global tools."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import signal
import socket
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.request import build_opener, ProxyHandler
import zipfile

ROOT = Path(__file__).resolve().parents[1]
PINS = json.loads((ROOT / 'runtime/bootstrap.json').read_text())
WINDOWS = os.name == 'nt'


def run(args, env, cwd=None):
    subprocess.run([str(value) for value in args], env=env, cwd=cwd, check=True)


def application_home():
    default = Path(os.environ['LOCALAPPDATA']) / 'MAPLEHarness' if WINDOWS else Path.home() / '.local/share/maple-harness'
    return Path(os.getenv('MAPLE_HOME', default)).expanduser().resolve()


def node_paths(home):
    machine = platform.machine().lower()
    arch = 'arm64' if machine in {'aarch64', 'arm64'} else 'x64'
    if machine not in {'amd64', 'x86_64', 'aarch64', 'arm64'} or (WINDOWS and arch != 'x64'):
        raise RuntimeError('Supported targets are Windows x64 and Linux x64/arm64.')
    name = f'node-v{PINS["node_version"]}-{"win" if WINDOWS else "linux"}-{arch}'
    directory = home / name
    binary = directory / ('node.exe' if WINDOWS else 'bin/node')
    corepack = directory / ('node_modules/corepack/dist/corepack.js' if WINDOWS else 'lib/node_modules/corepack/dist/corepack.js')
    return name, binary, corepack


def install_node(home):
    name, binary, corepack = node_paths(home)
    if binary.is_file() and corepack.is_file():
        return binary, corepack
    print('[2/5] Downloading and verifying Node.js...', flush=True)
    filename = name + ('.zip' if WINDOWS else '.tar.gz')
    base = f'https://nodejs.org/dist/v{PINS["node_version"]}/'
    with tempfile.TemporaryDirectory(prefix='maple-node-') as temp:
        archive = Path(temp) / filename
        opener = build_opener()
        with opener.open(base + 'SHASUMS256.txt', timeout=120) as response:
            expected = {line.split()[1]: line.split()[0] for line in response.read().decode().splitlines()}
        with opener.open(base + filename, timeout=120) as response, archive.open('wb') as output:
            shutil.copyfileobj(response, output)
        with archive.open('rb') as handle:
            if hashlib.file_digest(handle, 'sha256').hexdigest() != expected.get(filename):
                raise RuntimeError('Node.js checksum verification failed.')
        if WINDOWS:
            with zipfile.ZipFile(archive) as source:
                source.extractall(home)
        else:
            with tarfile.open(archive) as source:
                source.extractall(home, filter='data')
    return binary, corepack


def environment(home, node):
    env = os.environ.copy()
    env.update(MAPLE_HOME=str(home), PYTHONUTF8='1', PYTHONUNBUFFERED='1')
    for name, subdir in [('DSH_HOME', 'dsh-home'), ('COREPACK_HOME', 'corepack'),
                         ('LIVEOPT_MCP_STATE_DIR', 'state'), ('LIVEOPT_MCP_WORKSPACE_ROOT', 'workspace')]:
        env.setdefault(name, str(home / subdir))
    for name in ('DSH_HOME', 'LIVEOPT_MCP_STATE_DIR', 'LIVEOPT_MCP_WORKSPACE_ROOT'):
        Path(env[name]).mkdir(parents=True, exist_ok=True)
    env['PATH'] = os.pathsep.join([str(node.parent), str(home / 'bin'), env.get('PATH', '')])
    env.setdefault('NODE_USE_ENV_PROXY', '1')
    return env


def install(home, node, corepack, env):
    runtime = home / 'runtime'
    scripts = runtime / 'venv' / ('Scripts' if WINDOWS else 'bin')
    python = scripts / ('python.exe' if WINDOWS else 'python')
    mcp = scripts / ('liveopt-mcp.exe' if WINDOWS else 'liveopt-mcp')
    entry = home / 'dsh-runtime/node_modules/@deepseek-ai/dsh/lib/bin.js'
    marker = runtime / 'installed-manifest.json'
    manifest = (ROOT / 'RELEASE_MANIFEST.json').read_bytes()
    if marker.is_file() and marker.read_bytes() == manifest and python.is_file() and mcp.is_file() and entry.is_file():
        return python, mcp, entry
    print('[3/5] Installing the locked DSH runtime...', flush=True)
    host = home / 'dsh-runtime'
    host.mkdir(parents=True, exist_ok=True)
    for name in ('package.json', 'pnpm-lock.yaml', 'pnpm-workspace.yaml'):
        shutil.copy2(ROOT / 'runtime' / name, host / name)
    run([node, corepack, 'enable', '--install-directory', node.parent], env, host)
    run([node, corepack, 'prepare', f'pnpm@{PINS["pnpm_version"]}', '--activate'], env, host)
    run([node, corepack, 'pnpm', '--dir', host, 'install', '--frozen-lockfile'], env, host)
    print('[4/5] Installing Python optimization and document tools...', flush=True)
    runtime.mkdir(parents=True, exist_ok=True)
    run([sys.executable, '-m', 'venv', runtime / 'venv'], env)
    with tempfile.TemporaryDirectory(prefix='maple-install-') as temp:
        temp = Path(temp)
        core = Path(env.get('LIVEOPT_CORE_ROOT', ROOT / 'vendor/liveopt-core'))
        for source, destination in [(core, temp / 'core'), (ROOT, temp / 'plugin')]:
            destination.mkdir()
            shutil.copy2(source / 'pyproject.toml', destination / 'pyproject.toml')
        if (core / 'MANIFEST.in').is_file():
            shutil.copy2(core / 'MANIFEST.in', temp / 'core/MANIFEST.in')
        ignore = shutil.ignore_patterns('__pycache__', '*.pyc', '*.egg-info', 'build')
        for name in ('evo2', 'demo'):
            shutil.copytree(core / name, temp / 'core' / name, ignore=ignore)
        shutil.copytree(ROOT / 'src/liveopt_dsh', temp / 'plugin/src/liveopt_dsh', ignore=ignore)
        run([python, '-m', 'pip', 'install', '--upgrade', 'pip'], env)
        run([python, '-m', 'pip', 'wheel', '--no-deps', '--wheel-dir', temp / 'wheels', temp / 'core', temp / 'plugin'], env)
        wheels = sorted((temp / 'wheels').glob('*.whl'))
        run([python, '-m', 'pip', 'install', '--force-reinstall', '--no-deps', *wheels], env)
        run([python, '-m', 'pip', 'install', *wheels], env)
    bundle = runtime / 'dsh-bundle'
    if bundle.exists():
        shutil.rmtree(bundle)
    shutil.copytree(ROOT / 'dsh-bundle', bundle)
    run([node, entry, 'plugin', '--profile', 'web', 'add', bundle], env, env['LIVEOPT_MCP_WORKSPACE_ROOT'])
    bindir = home / 'bin'
    bindir.mkdir(exist_ok=True)
    if WINDOWS:
        (bindir / 'dsh.cmd').write_text(f'@echo off\r\nset "PATH={node.parent};%PATH%"\r\n"{node}" "{entry}" %*\r\n')
    else:
        import shlex
        for name, command in [('dsh', [node, entry]), ('liveopt-mcp', [mcp])]:
            wrapper = bindir / name
            wrapper.write_text('#!/bin/sh\nexport PATH=' + shlex.quote(str(node.parent)) + ':"$PATH"\nexec ' + shlex.join(map(str, command)) + ' "$@"\n')
            wrapper.chmod(0o755)
    marker.write_bytes(manifest)
    return python, mcp, entry


def free_port(preferred=0):
    for port in ([preferred] if preferred else []) + [0]:
        with socket.socket() as sock:
            try:
                sock.bind(('127.0.0.1', port))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError('No local port is available.')


def terminate(process):
    if process is None or process.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    try:
        process.wait(timeout=15)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def serve(home, node, python, mcp, entry, env, no_browser):
    env['LIVEOPT_MCP_COMMAND'] = str(mcp)
    port = free_port(int(env.get('MAPLE_PORT', 3000)))
    api_port = free_port()
    env['LIVEOPT_WEB_API_URL'] = f'http://127.0.0.1:{api_port}'
    env['LIVEOPT_WEB_API_PORT'] = str(api_port)
    if env.get('DEEPSEEK_API_KEY'):
        run([python, '-c', 'import os; from liveopt_dsh.app_settings import save_deepseek_api_key; save_deepseek_api_key(os.environ["DEEPSEEK_API_KEY"])'], env)
        env.pop('DEEPSEEK_API_KEY', None)
    children = []
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {'start_new_session': True}
    try:
        api = subprocess.Popen([str(python), '-m', 'liveopt_dsh.web_api', '--host', '127.0.0.1', '--port', str(api_port)], env=env, cwd=env['LIVEOPT_MCP_WORKSPACE_ROOT'], **options)
        children.append(api)
        opener = build_opener(ProxyHandler({}))
        for _ in range(100):
            if api.poll() is not None:
                raise RuntimeError('MAPLE application service failed to start.')
            try:
                with opener.open(env['LIVEOPT_WEB_API_URL'] + '/health', timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise RuntimeError('MAPLE application service did not become ready.')
        print(f'[5/5] Starting MAPLE on port {port}. Keep this window open. Press Ctrl+C to stop.', flush=True)
        args = [str(node), str(entry), '--profile', 'web', '--host', '127.0.0.1', '--port', str(port)]
        if no_browser or env.get('MAPLE_OPEN_BROWSER') == '0':
            args.append('--no-open')
        host = subprocess.Popen(args, env=env, cwd=env['LIVEOPT_MCP_WORKSPACE_ROOT'], **options)
        children.append(host)
        while host.poll() is None:
            if api.poll() is not None:
                raise RuntimeError('MAPLE application service stopped unexpectedly.')
            time.sleep(0.2)
        return host.returncode
    finally:
        for child in reversed(children):
            terminate(child)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--install-only', action='store_true')
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    home = application_home()
    home.mkdir(parents=True, exist_ok=True)
    node, corepack = install_node(home)
    env = environment(home, node)
    python, mcp, entry = install(home, node, corepack, env)
    if args.install_only:
        print('MAPLE installation complete. Run start.cmd or ./start.sh to open the application.')
        return 0
    return serve(home, node, python, mcp, entry, env, args.no_browser)


if __name__ == '__main__':
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(0)
    except Exception as error:
        print(f'MAPLE: {error}', file=sys.stderr)
        sys.exit(1)
