#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
if [[ "$MAPLE_TUNNEL" == named ]]; then
    exec "$MAPLE_CLOUDFLARED" tunnel --no-autoupdate --protocol http2 --edge-ip-version 4 \
        run --token-file "$P/secrets/cloudflare-token"
fi
[[ "$MAPLE_TUNNEL" == quick ]] || exit 0
exec {tunnel_output}< <(exec "$MAPLE_CLOUDFLARED" tunnel --no-autoupdate --protocol http2 --edge-ip-version 4 \
    --url "http://127.0.0.1:$MAPLE_GATEWAY_PORT" 2>&1)
tunnel_pid=$!
cleanup() {
    kill "$tunnel_pid" 2>/dev/null || true
    wait "$tunnel_pid" 2>/dev/null || true
}
trap cleanup EXIT
trap 'exit 143' TERM
trap 'exit 130' INT
while IFS= read -r line <&"$tunnel_output"; do
    echo "$line"
    # A deleted quick tunnel keeps retrying forever unless its process is replaced.
    if [[ "$line" == *"Unauthorized: Tunnel not found"* ]]; then
        echo "Quick tunnel is no longer registered; requesting a new public URL." >&2
        exit 1
    fi
    if [[ "$line" =~ (https://[a-z0-9-]+\.trycloudflare\.com) ]]; then
        url="${BASH_REMATCH[1]}"
        previous="$(cat "$P/public-url.txt" 2>/dev/null || true)"
        printf '%s\n' "$url" > "$P/public-url.txt"
        if [[ "$previous" != "$url" ]]; then
            systemctl --user --no-block try-restart "$MAPLE_SERVICE_PREFIX-front.service" || true
        fi
    fi
done
wait "$tunnel_pid"
