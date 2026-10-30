#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
if [[ "$MAPLE_TUNNEL" == named ]]; then
    exec "$MAPLE_CLOUDFLARED" tunnel --no-autoupdate --protocol http2 --edge-ip-version 4 \
        run --token-file "$P/secrets/cloudflare-token"
fi
[[ "$MAPLE_TUNNEL" == quick ]] || exit 0
"$MAPLE_CLOUDFLARED" tunnel --no-autoupdate --protocol http2 --edge-ip-version 4 \
    --url "http://127.0.0.1:$MAPLE_GATEWAY_PORT" 2>&1 |
while IFS= read -r line; do
    echo "$line"
    if [[ "$line" =~ (https://[a-z0-9-]+\.trycloudflare\.com) ]]; then
        url="${BASH_REMATCH[1]}"
        previous="$(cat "$P/public-url.txt" 2>/dev/null || true)"
        printf '%s\n' "$url" > "$P/public-url.txt"
        if [[ "$previous" != "$url" ]]; then
            systemctl --user --no-block try-restart "$MAPLE_SERVICE_PREFIX-front.service" || true
        fi
    fi
done
