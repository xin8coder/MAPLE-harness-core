#!/usr/bin/env bash
set -euo pipefail

CADDY_VERSION="${LIVEOPT_CADDY_VERSION:-2.11.4}"
CADDY_SHA512="8220d1f013b6f27510247b2360c9e0ca9f018feebd82515f07635318b34ff9777ccc8fd0b6e6f2486ce3a33fe389fbb7db12d05baa474f4587509fb4f5ebf1c9"
LOCAL_ROOT="${LIVEOPT_LOCAL_ROOT:-$HOME/.local/share/liveopt-dsh}"
CADDY_ROOT="$LOCAL_ROOT/caddy-${CADDY_VERSION}"

if [[ "$(uname -m)" != "x86_64" ]]; then
    echo "The pinned intranet Caddy bundle currently supports x86_64 only." >&2
    exit 2
fi

mkdir -p "$CADDY_ROOT"
if [[ ! -x "$CADDY_ROOT/caddy" ]]; then
    archive="$(mktemp "${TMPDIR:-/tmp}/caddy-${CADDY_VERSION}.XXXXXX.tar.gz")"
    trap 'rm -f "$archive"' EXIT
    curl --fail --location --retry 3 --output "$archive" \
        "https://github.com/caddyserver/caddy/releases/download/v${CADDY_VERSION}/caddy_${CADDY_VERSION}_linux_amd64.tar.gz"
    printf '%s  %s\n' "$CADDY_SHA512" "$archive" | sha512sum --check --status
    tar -xzf "$archive" -C "$CADDY_ROOT" caddy
    chmod 0755 "$CADDY_ROOT/caddy"
fi

"$CADDY_ROOT/caddy" version
echo "Intranet proxy is ready."
echo "Start with: $(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/start_intranet.sh"
