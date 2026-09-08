#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
LOCAL_ROOT="${LIVEOPT_LOCAL_ROOT:-$HOME/.local/share/liveopt-dsh}"
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
export LIVEOPT_WEB_API_PORT="${LIVEOPT_WEB_API_PORT:-8766}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$LOCAL_ROOT/caddy-data}"
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$LOCAL_ROOT/caddy-config}"

mkdir -p "$LOCAL_ROOT/logs"
LIVEOPT_DSH_HOST=127.0.0.1 \
LIVEOPT_DSH_PORT="$BACKEND_PORT" \
LIVEOPT_DSH_TRUSTED_HOST="${LIVEOPT_INTRANET_BIND}:${INTRANET_PORT}" \
"$SCRIPT_DIR/start_local.sh" >"$LOCAL_ROOT/logs/dsh-intranet.log" 2>&1 &
dsh_pid=$!
proxy_pid=""

cleanup() {
    if [[ -n "$proxy_pid" ]]; then kill "$proxy_pid" 2>/dev/null || true; fi
    kill "$dsh_pid" 2>/dev/null || true
    wait "$dsh_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

for _ in $(seq 1 60); do
    if curl --silent --fail --max-time 1 "http://127.0.0.1:${BACKEND_PORT}/" >/dev/null; then
        break
    fi
    if ! kill -0 "$dsh_pid" 2>/dev/null; then
        echo "DSH backend failed; see $LOCAL_ROOT/logs/dsh-intranet.log" >&2
        exit 2
    fi
    sleep 0.5
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${BACKEND_PORT}/" >/dev/null
for _ in $(seq 1 30); do
    if curl --silent --fail --max-time 1 "http://127.0.0.1:${LIVEOPT_WEB_API_PORT}/health" >/dev/null; then
        break
    fi
    sleep 0.2
done
curl --silent --fail --max-time 2 "http://127.0.0.1:${LIVEOPT_WEB_API_PORT}/health" >/dev/null

"$CADDY" run --config "$PLUGIN_ROOT/intranet/Caddyfile" --adapter caddyfile &
proxy_pid=$!
echo "LiveOpt Harness intranet UI: https://${LIVEOPT_INTRANET_BIND}:${INTRANET_PORT}"
wait "$proxy_pid"
