#!/usr/bin/env bash
set -euo pipefail

LOCAL_ROOT="${LIVEOPT_LOCAL_ROOT:-$HOME/.local/share/liveopt-dsh}"
BIN_DIR="${LIVEOPT_DSH_BIN_DIR:-$HOME/.local/bin}"
PROFILE="${LIVEOPT_DSH_PROFILE:-web}"
HOST="${LIVEOPT_DSH_HOST:-127.0.0.1}"
PORT="${LIVEOPT_DSH_PORT:-3000}"
WEB_API_HOST="${LIVEOPT_WEB_API_HOST:-127.0.0.1}"
WEB_API_PORT="${LIVEOPT_WEB_API_PORT:-8766}"

if [[ -n "${LIVEOPT_ENV_FILE:-}" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$LIVEOPT_ENV_FILE"
    set +a
fi

export PATH="$BIN_DIR:$PATH"
export LIVEOPT_MCP_STATE_DIR="${LIVEOPT_MCP_STATE_DIR:-$LOCAL_ROOT/state}"
export LIVEOPT_MCP_WORKSPACE_ROOT="${LIVEOPT_MCP_WORKSPACE_ROOT:-$PWD}"
export LIVEOPT_MCP_CACHE_MODE="${LIVEOPT_MCP_CACHE_MODE:-read_write}"
export LIVEOPT_MCP_NETWORK_MODE="${LIVEOPT_MCP_NETWORK_MODE:-auto}"
export LIVEOPT_MCP_DEFAULT_MODEL="deepseek-v4-flash"
export DEEPSEEK_MODEL="deepseek-v4-flash"
export LLM_PROVIDER="deepseek"
export NODE_USE_ENV_PROXY="${NODE_USE_ENV_PROXY:-1}"

if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
    # Migrate the launch-time key into Harness' owner-only credential store so
    # the LiveOpt Settings page can replace it without restarting the app.
    liveopt-configure --state-dir "$LIVEOPT_MCP_STATE_DIR" --api-key "$DEEPSEEK_API_KEY" >/dev/null
    unset DEEPSEEK_API_KEY
fi

dsh_args=(--profile "$PROFILE" --host "$HOST" --port "$PORT" --no-open)
if [[ -n "${LIVEOPT_DSH_TRUSTED_HOST:-}" ]]; then
    dsh_args+=(--trusted-host "$LIVEOPT_DSH_TRUSTED_HOST")
fi

liveopt-web-api --host "$WEB_API_HOST" --port "$WEB_API_PORT" &
web_api_pid=$!
dsh "${dsh_args[@]}" &
dsh_pid=$!
cleanup() {
    kill "$dsh_pid" 2>/dev/null || true
    kill "$web_api_pid" 2>/dev/null || true
    wait "$dsh_pid" 2>/dev/null || true
    wait "$web_api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

wait "$dsh_pid"
