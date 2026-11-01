#!/usr/bin/env python3
"""Install an opt-in Linux sandbox outside the checkout; never accept keys in argv."""
import argparse
import getpass
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import shutil
import subprocess
import sys
from urllib.parse import urlsplit

SOURCE = Path(__file__).resolve().parent
CHECKOUT = SOURCE.parents[1]


def validate_values(values):
    address = ipaddress.ip_address(values['MAPLE_BIND'])
    if address.version != 4 or address.is_unspecified or not (address.is_private or address.is_loopback):
        raise ValueError('Choose a loopback or private IPv4 bind address')
    ports = [int(values[key]) for key in ('MAPLE_PORT', 'MAPLE_GATEWAY_PORT', 'MAPLE_AUTH_PORT',
                                         'MAPLE_MODEL_PORT', 'MAPLE_WEB_PORT', 'MAPLE_API_PORT')]
    if len(set(ports)) != len(ports) or any(not 1024 <= port <= 65535 for port in ports):
        raise ValueError('Choose distinct unprivileged ports between 1024 and 65535')
    if not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', values['MAPLE_SERVICE_PREFIX']):
        raise ValueError('Invalid service prefix')
    if values['MAPLE_TUNNEL'] not in {'none', 'quick', 'named'}:
        raise ValueError('Unknown tunnel mode')
    origin = values['MAPLE_PUBLIC_ORIGIN']
    parsed = urlsplit(origin)
    if origin and (parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password
                   or parsed.path or parsed.query or parsed.fragment or any(char.isspace() for char in origin)):
        raise ValueError('Public origin must be a plain HTTPS origin, without a path or credentials')
    if origin:
        hostname = parsed.hostname.encode('idna').decode('ascii')
        if not re.fullmatch(r'[A-Za-z0-9.-]+', hostname):
            raise ValueError('Invalid public hostname')
        port = parsed.port
        if port is not None and not 1 <= port <= 65535:
            raise ValueError('Invalid public port')
        values['MAPLE_PUBLIC_ORIGIN'] = 'https://'+hostname+(f':{port}' if port else '')
    if values['MAPLE_TUNNEL'] == 'named' and not origin:
        raise ValueError('Named tunnels require --public-origin')
    values['MAPLE_INTRANET_ORIGIN'] = f"https://{address}:{values['MAPLE_PORT']}"
    return values


def write_private(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    path.chmod(0o600)


def write_env(path, values):
    write_private(path, ''.join(f'{key}={shlex.quote(str(value))}\n' for key, value in values.items()))


def prepare(root, values, *, api_key, password, username='admin', tunnel_token=None):
    root = Path(root).expanduser().resolve()
    if root == CHECKOUT or CHECKOUT in root.parents:
        raise ValueError('Sandbox data must be outside the source checkout')
    if any(char.isspace() or ord(char) < 32 for char in str(root)):
        raise ValueError('The sandbox installation path must not contain whitespace')
    if len(str(root/'run/llm/llm.sock').encode()) > 100:
        raise ValueError('Choose a shorter sandbox directory for Linux Unix sockets')
    if (root/'config.env').exists():
        raise FileExistsError('Existing sandbox: use --update to preserve credentials and data')
    if not api_key.strip() or not password or not username.strip():
        raise ValueError('API key, username, and password must not be empty')
    validate_values(values)
    if values['MAPLE_TUNNEL'] == 'named' and (not tunnel_token or not tunnel_token.strip()):
        raise ValueError('Named tunnels require a token file')
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    for folder in ('secrets', 'conf', 'run/llm', 'run/web', 'logs', 'data/home', 'data/local',
                   'data/workspace', 'data/dsh-home', 'data/state', 'systemd'):
        directory = root/folder
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
    values = {**values, 'MAPLE_SANDBOX_ROOT': str(root)}
    write_private(root/'settings.json', json.dumps(values, indent=2)+'\n')
    write_env(root/'config.env', values)
    salt = secrets.token_bytes(24)
    write_env(root/'secrets/front.env', {
        'MAPLE_FRONT_USER': username, 'MAPLE_FRONT_SALT': salt.hex(),
        'MAPLE_FRONT_PBKDF2': hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 200_000).hex(),
        'MAPLE_SESSION_SECRET': secrets.token_hex(32),
    })
    write_env(root/'secrets/llm.env', {'MAPLE_LLM_KEY': api_key.strip()})
    if values['MAPLE_TUNNEL'] == 'named':
        write_private(root/'secrets/cloudflare-token', tunnel_token.strip()+'\n')
    # A real key is deliberately never placed in the application's DSH home.
    write_private(root/'data/dsh-home/.credentials.yaml',
                  'version: 1\nrefs:\n  DEEPSEEK_API_KEY: sk-sandbox-placeholder\n')
    uid, gid = os.getuid(), os.getgid()
    write_private(root/'conf/passwd', f'root:x:0:0:root:/root:/bin/false\nmaple:x:{uid}:{gid}:MAPLE:/data/home:/bin/bash\nnobody:x:65534:65534:nobody:/:/bin/false\n')
    write_private(root/'conf/group', f'root:x:0:\nmaple:x:{gid}:\nnogroup:x:65534:\n')
    write_private(root/'conf/hosts', '127.0.0.1 localhost maple\n::1 localhost\n')
    install_assets(root)
    return values


def install_assets(root):
    if SOURCE != root/'app':
        shutil.copytree(SOURCE, root/'app', dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'node_modules'))
    assets = CHECKOUT/'src/liveopt_dsh/assets'
    public = root/'app/public'
    public.mkdir(exist_ok=True)
    for name in ('lanchou-logo.png', 'echarts.min.js', 'lucide.min.js',
                 'ECHARTS-LICENSE', 'ECHARTS-NOTICE', 'LUCIDE-LICENSE'):
        source = assets/name if name == 'lanchou-logo.png' else assets/'explorer'/name
        if source.is_file():
            shutil.copy2(source, public/name)
    for path in (root/'app').rglob('*.sh'):
        path.chmod(0o700)
    for name in ('Caddyfile.front', 'Caddyfile.llm'):
        shutil.copyfile(SOURCE/name, root/'conf'/name)
        (root/'conf'/name).chmod(0o600)


def unit_texts(root, values):
    prefix = values['MAPLE_SERVICE_PREFIX']
    names = ['llm', 'auth', 'sandbox', 'front']
    if values['MAPLE_TUNNEL'] != 'none':
        names.append('tunnel')
    units = {}
    for name in names:
        script = 'sandbox.sh' if name == 'sandbox' else f'start-{name}.sh'
        dependencies = ''
        if name == 'sandbox':
            dependencies = f'After={prefix}-llm.service\nRequires={prefix}-llm.service\n'
        if name == 'front':
            dependencies = (f'After={prefix}-sandbox.service {prefix}-auth.service\n'
                            f'BindsTo={prefix}-sandbox.service\nRequires={prefix}-auth.service\n')
        if name == 'tunnel':
            dependencies = f'After={prefix}-front.service network-online.target\n'
        units[f'{prefix}-{name}.service'] = (
            f'[Unit]\nDescription=lanchou sandbox: {name}\nPartOf={prefix}.target\n{dependencies}\n'
            f'[Service]\nType=simple\nExecStart=/bin/bash {root}/app/{script}\n'
            f'StandardOutput=append:{root}/logs/{name}.log\nStandardError=append:{root}/logs/{name}.log\n'
            'Restart=on-failure\nRestartSec=5\nKillMode=control-group\nTimeoutStopSec=25\nUMask=0077\n\n'
            f'[Install]\nWantedBy={prefix}.target\n')
    wants = ' '.join(f'{prefix}-{name}.service' for name in names)
    units[f'{prefix}.target'] = (f'[Unit]\nDescription=lanchou sandbox application\nWants={wants}\n'
                                'After=network-online.target\n\n[Install]\nWantedBy=default.target\n')
    return units


def initialize_profile(root, values):
    env = {key: value for key, value in os.environ.items()
           if key not in {'DEEPSEEK_API_KEY', 'KIMI_API_KEY', 'LIVEOPT_ENV_FILE', 'DSH_HOME', 'PYTHONPATH'}}
    home = Path(values['MAPLE_HOME'])
    env.update(DSH_HOME=str(root/'data/dsh-home'),
               PATH=str(home/'bin')+os.pathsep+env.get('PATH', ''),
               DEEPSEEK_API_KEY='sk-sandbox-placeholder', DSH_TELEMETRY_DISABLED='1')
    subprocess.run([str(home/'bin/dsh'), 'plugin', '--profile', 'web', 'add', str(home/'runtime/dsh-bundle')],
                   env=env, cwd=root/'data/workspace', check=True, stdout=subprocess.DEVNULL)


def validate_unit_ownership(directory, root, units):
    for name in units:
        path = directory/name
        if name.endswith('.service') and path.exists() and f'{root}/app/' not in path.read_text():
            raise ValueError('The service prefix belongs to another installation; choose --service-prefix')


def main():
    if sys.platform != 'linux':
        raise SystemExit('The sandbox server requires Linux. Windows can use the web or remote desktop client.')
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path.home()/'.local/share/maple-sandbox')
    parser.add_argument('--maple-home', type=Path, default=Path(os.getenv('MAPLE_HOME', Path.home()/'.local/share/maple-harness')))
    parser.add_argument('--bind', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=3000)
    parser.add_argument('--gateway-port', type=int, default=18990)
    parser.add_argument('--auth-port', type=int, default=18991)
    parser.add_argument('--model-port', type=int, default=18080)
    parser.add_argument('--web-port', type=int, default=3101)
    parser.add_argument('--api-port', type=int, default=3102)
    parser.add_argument('--username', default='admin')
    parser.add_argument('--caddy', type=Path)
    parser.add_argument('--tunnel', choices=['none', 'quick', 'named'], default='none')
    parser.add_argument('--cloudflared', default='cloudflared')
    parser.add_argument('--public-origin', default='')
    parser.add_argument('--tunnel-token-file', type=Path)
    parser.add_argument('--service-prefix', default='maple-sandbox')
    parser.add_argument('--reuse-api-key', action='store_true')
    parser.add_argument('--update', action='store_true')
    parser.add_argument('--start', action='store_true')
    parser.add_argument('--no-register', action='store_true', help='Prepare files but do not register user services')
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    home = args.maple_home.expanduser().resolve()
    for binary in ('bwrap', 'curl', 'bash'):
        if not shutil.which(binary):
            raise SystemExit(f'Missing {binary}; install the Linux prerequisite before deployment')
    if args.update:
        values = validate_values(json.loads((root/'settings.json').read_text()))
    else:
        caddy = (args.caddy or home/'caddy-2.11.4/caddy').expanduser().resolve()
        values = validate_values({'MAPLE_HOME': str(home), 'MAPLE_CADDY': str(caddy), 'MAPLE_BIND': args.bind,
            'MAPLE_PORT': args.port, 'MAPLE_GATEWAY_PORT': args.gateway_port, 'MAPLE_AUTH_PORT': args.auth_port,
            'MAPLE_MODEL_PORT': args.model_port, 'MAPLE_WEB_PORT': args.web_port, 'MAPLE_API_PORT': args.api_port,
            'MAPLE_TUNNEL': args.tunnel, 'MAPLE_CLOUDFLARED': shutil.which(args.cloudflared) or args.cloudflared,
            'MAPLE_PUBLIC_ORIGIN': args.public_origin.rstrip('/'), 'MAPLE_SERVICE_PREFIX': args.service_prefix})
    home = Path(values['MAPLE_HOME'])
    for path in (home/'bin/dsh', home/'runtime/venv/bin/python', Path(values['MAPLE_CADDY'])):
        if not path.is_file():
            raise SystemExit('Install the native MAPLE runtime and Caddy first; missing: '+str(path))
    if values['MAPLE_TUNNEL'] != 'none' and not shutil.which(values['MAPLE_CLOUDFLARED']):
        raise SystemExit('Install cloudflared before enabling a public tunnel')
    if args.start and args.no_register:
        raise SystemExit('--start and --no-register cannot be combined')
    target = values['MAPLE_SERVICE_PREFIX']+'.target'
    units = unit_texts(root, values)
    if not args.no_register:
        validate_unit_ownership(Path.home()/'.config/systemd/user', root, units)
    active = subprocess.run(['systemctl', '--user', 'is-active', '--quiet', target]).returncode == 0 if args.update else False
    if args.update:
        if active:
            subprocess.run(['systemctl', '--user', 'stop', target], check=True)
        install_assets(root)
    else:
        key = ''
        if args.reuse_api_key:
            import yaml
            document = yaml.safe_load((home/'dsh-home/.credentials.yaml').read_text())
            key = document.get('refs', {}).get('DEEPSEEK_API_KEY', '')
        key = key or getpass.getpass('DeepSeek API key (stored outside the sandbox): ')
        password = getpass.getpass('New lanchou login password: ')
        if password != getpass.getpass('Confirm login password: '):
            raise SystemExit('Passwords do not match')
        tunnel_token = args.tunnel_token_file.read_text() if args.tunnel_token_file else None
        values = prepare(root, values, api_key=key, password=password,
                         username=args.username, tunnel_token=tunnel_token)
        initialize_profile(root, values)
    for name, text in units.items():
        write_private(root/'systemd'/name, text)
        if not args.no_register:
            write_private(Path.home()/'.config/systemd/user'/name, text)
    if not args.no_register:
        subprocess.run(['systemctl', '--user', 'daemon-reload'], check=True)
        if args.start or active:
            subprocess.run(['systemctl', '--user', 'enable', '--now', target], check=True)
    print('lanchou sandbox prepared at '+str(root))
    print('Intranet address: '+values['MAPLE_INTRANET_ORIGIN'])
    print('Back up this private directory; do not upload its secrets, data, or logs.')


if __name__ == '__main__':
    main()
