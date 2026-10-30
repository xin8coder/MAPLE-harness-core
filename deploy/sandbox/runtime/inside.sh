#!/usr/bin/env bash
set -euo pipefail
python="$MAPLE_HOME/runtime/venv/bin/python"
"$python" /opt/maple-sandbox/fwd.py /run/maple/llm/llm.sock /run/maple/web/web.sock "$MAPLE_MODEL_PORT" "$MAPLE_WEB_PORT" &
bridge_pid=$!
"$MAPLE_HOME/runtime/venv/bin/liveopt-web-api" --host 127.0.0.1 --port "$MAPLE_API_PORT" &
api_pid=$!
dsh_pid=""
cleanup() {
    kill "$bridge_pid" "$api_pid" ${dsh_pid:+"$dsh_pid"} 2>/dev/null || true
    wait "$bridge_pid" "$api_pid" ${dsh_pid:+"$dsh_pid"} 2>/dev/null || true
}
trap cleanup EXIT INT TERM
for _ in $(seq 1 100); do
    curl --noproxy '*' --silent --fail "$LIVEOPT_WEB_API_URL/health" >/dev/null && break
    kill -0 "$api_pid" 2>/dev/null || exit 1
    sleep 0.1
done
curl --noproxy '*' --silent --fail "$LIVEOPT_WEB_API_URL/health" >/dev/null
"$MAPLE_HOME/bin/dsh" --profile web --host 127.0.0.1 --port "$MAPLE_WEB_PORT" --no-open &
dsh_pid=$!
wait "$dsh_pid"
