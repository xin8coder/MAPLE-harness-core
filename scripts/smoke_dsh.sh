#!/usr/bin/env bash
set -euo pipefail

command -v dsh >/dev/null 2>&1 || { echo "dsh is required" >&2; exit 2; }
command -v liveopt-mcp >/dev/null 2>&1 || { echo "liveopt-mcp is required" >&2; exit 2; }

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
TMP_ROOT="$(mktemp -d /tmp/liveopt-dsh-smoke.XXXXXX)"
REQUEST_LOG="$TMP_ROOT/requests.jsonl"
OUTPUT_LOG="$TMP_ROOT/output.txt"
ERROR_LOG="$TMP_ROOT/error.txt"
PORT="$(python3 - <<'PY'
import socket
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    print(sock.getsockname()[1])
PY
)"

cleanup() {
    if [[ -n "${MOCK_PID:-}" ]]; then
        kill "$MOCK_PID" 2>/dev/null || true
        wait "$MOCK_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

DSH_HOME="$TMP_ROOT/dsh-home" dsh plugin --profile headless add "$PLUGIN_ROOT/dsh-bundle" >/dev/null
python3 "$PLUGIN_ROOT/tests/mock_dsh_llm.py" --port "$PORT" --requests "$REQUEST_LOG" &
MOCK_PID=$!

for _ in $(seq 1 50); do
    python3 - "$PORT" <<'PY' >/dev/null 2>&1 && break || true
import socket, sys
with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=0.1):
    pass
PY
    sleep 0.1
done

DSH_HOME="$TMP_ROOT/dsh-home" \
LIVEOPT_MCP_COMMAND="$(command -v liveopt-mcp)" \
LIVEOPT_MCP_STATE_DIR="$TMP_ROOT/state" \
LIVEOPT_MCP_WORKSPACE_ROOT="${LIVEOPT_MCP_WORKSPACE_ROOT:-$PWD}" \
DEEPSEEK_API_KEY=mock-key \
DEEPSEEK_BASE_URL="http://127.0.0.1:$PORT/v1" \
dsh --profile headless "Exercise one LiveOpt MCP tool." >"$OUTPUT_LOG" 2>"$ERROR_LOG"

grep -q 'mcp__liveopt__liveopt_cancel' "$REQUEST_LOG"
grep -q '"liveopt_skill_visible": true' "$REQUEST_LOG"
grep -q 'LiveOpt MCP tool-call path completed' "$OUTPUT_LOG"
echo "DSH -> LiveOpt MCP tool-call smoke passed"
