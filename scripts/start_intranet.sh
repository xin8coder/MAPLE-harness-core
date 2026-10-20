#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOCAL_ROOT="$LIVEOPT_LOCAL_ROOT"
CADDY_VERSION="${LIVEOPT_CADDY_VERSION:-2.11.4}"
CADDY="$LOCAL_ROOT/caddy-${CADDY_VERSION}/caddy"
BACKEND_PORT="${LIVEOPT_DSH_BACKEND_PORT:-3001}"
INTRANET_PORT="${LIVEOPT_INTRANET_PORT:-3000}"

if [[ ! -x "$CADDY" ]]; then
    echo "Run $SCRIPT_DIR/bootstrap_intranet.sh first." >&2
    exit 2
fi

if [[ -n "${LIVEOPT_ENV_FILE:-}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$LIVEOPT_ENV_FILE"
    set +a
fi

LIVEOPT_INTRANET_BIND="${LIVEOPT_INTRANET_BIND:-$(ip -4 route get 1.1.1.1 | awk '{for (i=1; i<=NF; i++) if ($i=="src") {print $(i+1); exit}}')}"
case "$LIVEOPT_INTRANET_BIND" in
    10.*|192.168.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) ;;
    *) echo "Refusing non-private intranet bind address: $LIVEOPT_INTRANET_BIND" >&2; exit 2 ;;
esac

LIVEOPT_INTRANET_PORT="$INTRANET_PORT"
export LIVEOPT_INTRANET_BIND LIVEOPT_INTRANET_PORT BACKEND_PORT
export LIVEOPT_DSH_BACKEND_PORT="$BACKEND_PORT"
export LIVEOPT_WEB_API_HOST="127.0.0.1"
export XDG_DATA_HOME="${LIVEOPT_CADDY_DATA_HOME:-$LOCAL_ROOT/caddy-data}"
export XDG_CONFIG_HOME="${LIVEOPT_CADDY_CONFIG_HOME:-$LOCAL_ROOT/caddy-config}"

mkdir -p "$LOCAL_ROOT/logs"
LIVEOPT_DSH_HOST=127.0.0.1 \
MAPLE_PORT="$BACKEND_PORT" \
LIVEOPT_DSH_PORT="$BACKEND_PORT" \
LIVEOPT_DSH_TRUSTED_HOST="${LIVEOPT_INTRANET_BIND}:${INTRANET_PORT}" \
LIVEOPT_DSH_PUBLIC_URL="https://${LIVEOPT_INTRANET_BIND}:${INTRANET_PORT}/" \
"$SCRIPT_DIR/start_local.sh" >"$LOCAL_ROOT/logs/dsh-intranet.log" 2>&1 &
dsh_pid=$!
proxy_pid=""

cleanup() {
    if [[ -n "$proxy_pid" ]]; then kill "$proxy_pid" 2>/dev/null || true; fi
    kill "$dsh_pid" 2>/dev/null || true
    wait "$dsh_pid" 2>/dev/null || true
    if [[ -n "$proxy_pid" ]]; then wait "$proxy_pid" 2>/dev/null || true; fi
}
trap cleanup EXIT INT TERM

backend_ready() {
    local status
    status="$(curl --noproxy '*' --silent --max-time 1 --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:${BACKEND_PORT}/")" || return 1
    # Remote profiles require browser pairing even for their index page.
    [[ "$status" == 200 || "$status" == 401 ]]
}

for _ in $(seq 1 60); do
    if backend_ready; then
        break
    fi
    if ! kill -0 "$dsh_pid" 2>/dev/null; then
        echo "DSH backend failed; see $LOCAL_ROOT/logs/dsh-intranet.log" >&2
        exit 2
    fi
    sleep 0.5
done
backend_ready || { echo "DSH backend did not become ready." >&2; exit 2; }

"$CADDY" run --config "$PLUGIN_ROOT/intranet/Caddyfile" --adapter caddyfile &
proxy_pid=$!
echo "LiveOpt Harness intranet UI: https://${LIVEOPT_INTRANET_BIND}:${INTRANET_PORT}"
wait "$proxy_pid"
