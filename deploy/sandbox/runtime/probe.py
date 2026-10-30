"""Offline isolation checks, run inside the sandbox after the model proxy starts."""
import http.client
import json
import os
from pathlib import Path
import socket
import tempfile


class UnixConnection(http.client.HTTPConnection):
    def connect(self):
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(3)
        self.sock.connect('/run/maple/llm/llm.sock')


def main():
    runtime = Path(os.environ['MAPLE_HOME'])
    checks = {'host_credentials_absent': not (runtime/'dsh-home/.credentials.yaml').exists(),
              'host_state_absent': not (runtime/'state').exists(),
              'host_data_disks_absent': not Path('/mnt/data2').exists(),
              'placeholder_only': 'sk-sandbox-placeholder' in Path('/data/dsh-home/.credentials.yaml').read_text()}
    try:
        with socket.create_connection(('1.1.1.1', 443), timeout=.5):
            checks['internet_blocked'] = False
    except OSError:
        checks['internet_blocked'] = True
    try:
        with tempfile.NamedTemporaryFile(dir=runtime/'runtime'):
            checks['runtime_read_only'] = False
    except OSError:
        checks['runtime_read_only'] = True
    with tempfile.NamedTemporaryFile(dir='/data'):
        checks['app_data_writable'] = True
    connection = UnixConnection('localhost')
    connection.request('GET', '/user/balance')
    checks['proxy_blocks_non_model_paths'] = connection.getresponse().status == 403
    connection.close()
    print(json.dumps(checks, sort_keys=True))
    if not all(checks.values()):
        raise SystemExit('Sandbox isolation check failed')


if __name__ == '__main__':
    main()
