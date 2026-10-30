#!/usr/bin/env bash
# Start the login proxy once the sandboxed DSH has printed its pairing token.
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"

for _ in $(seq 1 120); do
    line="$(grep -a 'dsh web:' "$P/logs/sandbox.log" 2>/dev/null | tail -1 || true)"
    token="${line##*token=}"
    if [[ -n "$line" && "$token" != "$line" && -S "$P/run/web/web.sock" ]]; then
        # A stale log line/socket can survive a restart. Admit this token only
        # when the current sandbox actually accepts it. Keep it out of argv.
        status="$(curl --noproxy '*' --silent --max-time 2 \
            --unix-socket "$P/run/web/web.sock" --output /dev/null \
            --write-out '%{http_code}' --config - <<EOF
url = "http://127.0.0.1:$MAPLE_WEB_PORT/?token=$token"
EOF
        )" || true
        [[ "$status" == 302 || "$status" == 303 || "$status" == 307 ]] && break
    fi
    sleep 1
done
token="${line##*token=}"
[[ -n "$token" && "$token" != "$line" ]] || { echo "no DSH token yet" >&2; exit 1; }
[[ "${status:-}" == 302 || "${status:-}" == 303 || "${status:-}" == 307 ]] || { echo "sandbox did not accept its current pairing token" >&2; exit 1; }

export DSH_TOKEN="$token"
if [[ "$MAPLE_TUNNEL" == quick && -f "$P/public-url.txt" ]]; then
    export MAPLE_PUBLIC_ORIGIN="$(cat "$P/public-url.txt")"
fi
export XDG_DATA_HOME="$P/run/caddy-front" XDG_CONFIG_HOME="$P/run/caddy-front"
exec "$MAPLE_CADDY" run --config "$P/conf/Caddyfile.front" --adapter caddyfile
