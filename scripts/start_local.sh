#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"
if [[ -n "${LIVEOPT_ENV_FILE:-}" ]]; then
  set -a
  source "$LIVEOPT_ENV_FILE"
  set +a
fi
[[ -x "$LIVEOPT_DSH_BIN_DIR/liveopt-mcp" ]] || { echo "Run ./maple to install the application first." >&2; exit 2; }
mkdir -p "$LIVEOPT_MCP_WORKSPACE_ROOT"
export LIVEOPT_MCP_COMMAND="$LIVEOPT_DSH_BIN_DIR/liveopt-mcp"
export LIVEOPT_WEB_API_PORT="${LIVEOPT_WEB_API_PORT:-$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1]); s.close()')}"
export LIVEOPT_WEB_API_URL="http://127.0.0.1:$LIVEOPT_WEB_API_PORT"
export NODE_USE_ENV_PROXY="${NODE_USE_ENV_PROXY:-1}"
if [[ -n "${DEEPSEEK_API_KEY:-}" ]]; then
  liveopt-configure --api-key "$DEEPSEEK_API_KEY" >/dev/null
  unset DEEPSEEK_API_KEY
fi
liveopt-web-api --host 127.0.0.1 --port "$LIVEOPT_WEB_API_PORT" &
api_pid=$!
dsh_pid=""
cleanup() {
  [[ -z "$dsh_pid" ]] || kill "$dsh_pid" 2>/dev/null || true
  kill "$api_pid" 2>/dev/null || true
  [[ -z "$dsh_pid" ]] || wait "$dsh_pid" 2>/dev/null || true
  wait "$api_pid" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
for _ in $(seq 1 100); do
  curl --noproxy '*' --silent --fail "$LIVEOPT_WEB_API_URL/health" >/dev/null && break
  kill -0 "$api_pid" 2>/dev/null || { echo "MAPLE service failed to start." >&2; exit 2; }
  sleep 0.1
done
curl --noproxy '*' --silent --fail "$LIVEOPT_WEB_API_URL/health" >/dev/null
args=(--profile "$LIVEOPT_DSH_PROFILE" --host "${LIVEOPT_DSH_HOST:-127.0.0.1}" --port "${MAPLE_PORT:-${LIVEOPT_DSH_PORT:-3000}}" --no-open)
[[ -z "${LIVEOPT_DSH_TRUSTED_HOST:-}" ]] || args+=(--trusted-host "$LIVEOPT_DSH_TRUSTED_HOST")
[[ -z "${LIVEOPT_DSH_PUBLIC_URL:-}" ]] || args+=(--public-url "$LIVEOPT_DSH_PUBLIC_URL")
cd "$LIVEOPT_MCP_WORKSPACE_ROOT"
dsh "${args[@]}" &
dsh_pid=$!
wait "$dsh_pid"
