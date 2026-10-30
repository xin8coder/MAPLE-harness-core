#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
set -a
source "$P/secrets/llm.env"
set +a
export XDG_DATA_HOME="$P/run/caddy-llm" XDG_CONFIG_HOME="$P/run/caddy-llm"
rm -f "$P/run/llm/llm.sock"
exec "$MAPLE_CADDY" run --config "$P/conf/Caddyfile.llm" --adapter caddyfile
