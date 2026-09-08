#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
UNIT_SOURCE="$PLUGIN_ROOT/systemd/liveopt-intranet.service"
UNIT_ROOT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT_TARGET="$UNIT_ROOT/liveopt-intranet.service"
CONFIG_ROOT="${LIVEOPT_CONFIG_ROOT:-$HOME/.config/liveopt-dsh}"
SERVICE_ENV="$CONFIG_ROOT/service.env"

mkdir -p "$UNIT_ROOT"
"${PYTHON_BIN:-python3}" - "$UNIT_SOURCE" "$UNIT_TARGET" "$PLUGIN_ROOT" <<'UNIT_PY'
from pathlib import Path
import os
import sys
source, target, plugin_root = sys.argv[1:]
# Quote the checkout path for systemd, including spaces and percent specifiers.
quoted = plugin_root.replace("\\", "\\\\").replace('"', '\\"').replace("%", "%%")
Path(target).write_text(Path(source).read_text().replace("@PLUGIN_ROOT@", quoted))
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
systemctl --user enable --now liveopt-intranet.service

echo "Installed and started: liveopt-intranet.service"
echo "Status: systemctl --user status liveopt-intranet.service"
echo "Logs:   journalctl --user -u liveopt-intranet.service -f"
echo "Network environment: $SERVICE_ENV"
