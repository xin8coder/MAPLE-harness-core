#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
UNIT_SOURCE="$PLUGIN_ROOT/systemd/maple-intranet.service"
UNIT_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_TARGET="$UNIT_ROOT/maple-intranet.service"
CONFIG_ROOT="${LIVEOPT_CONFIG_ROOT:-$HOME/.config/maple-harness}"
SERVICE_ENV="$CONFIG_ROOT/service.env"

mkdir -p "$UNIT_ROOT"
"${PYTHON_BIN:-python3}" - "$UNIT_SOURCE" "$UNIT_TARGET" "$PLUGIN_ROOT" "$LIVEOPT_LOCAL_ROOT" "$CONFIG_ROOT" <<'UNIT_PY'
from pathlib import Path
import os
import sys
source, target, plugin_root, maple_home, config_root = sys.argv[1:]
# Quote the checkout path for systemd, including spaces and percent specifiers.
content = Path(source).read_text()
for marker, value in {'PLUGIN_ROOT': plugin_root, 'MAPLE_HOME': maple_home, 'CONFIG_ROOT': config_root}.items():
    quoted = value.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
    content = content.replace(f'@{marker}@', quoted)
Path(target).write_text(content)
os.chmod(target, 0o644)
UNIT_PY
if [[ ! -f "$SERVICE_ENV" ]] && [[ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]]; then
    proxy="${HTTPS_PROXY:-${https_proxy:-}}"
    no_proxy="${NO_PROXY:-${no_proxy:-127.0.0.1,localhost}}"
    mkdir -p "$CONFIG_ROOT"
    umask 077
    {
        printf 'HTTP_PROXY=%s\n' "$proxy"
        printf 'HTTPS_PROXY=%s\n' "$proxy"
        printf 'http_proxy=%s\n' "$proxy"
        printf 'https_proxy=%s\n' "$proxy"
        printf 'NO_PROXY=%s\n' "$no_proxy"
        printf 'no_proxy=%s\n' "$no_proxy"
    } >"$SERVICE_ENV"
fi
systemctl --user daemon-reload
systemctl --user enable --now maple-intranet.service

echo "Installed and started: maple-intranet.service"
echo "Status: systemctl --user status maple-intranet.service"
echo "Logs:   journalctl --user -u maple-intranet.service -f"
echo "Network environment: $SERVICE_ENV"
