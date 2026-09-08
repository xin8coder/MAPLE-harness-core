#!/usr/bin/env bash
set -euo pipefail

NODE_VERSION="${LIVEOPT_NODE_VERSION:-24.19.0}"
PNPM_VERSION="${LIVEOPT_PNPM_VERSION:-11.7.0}"
DSH_VERSION="${LIVEOPT_DSH_VERSION:-0.1.0-rc.8}"
PROFILE="${LIVEOPT_DSH_PROFILE:-web}"
LOCAL_ROOT="${LIVEOPT_LOCAL_ROOT:-$HOME/.local/share/liveopt-dsh}"
BIN_DIR="${LIVEOPT_DSH_BIN_DIR:-$HOME/.local/bin}"

case "$(uname -m)" in
    x86_64) NODE_ARCH="x64" ;;
    aarch64|arm64) NODE_ARCH="arm64" ;;
    *) echo "Unsupported CPU architecture: $(uname -m)" >&2; exit 2 ;;
esac

NODE_DIST="node-v${NODE_VERSION}-linux-${NODE_ARCH}"
NODE_ROOT="$LOCAL_ROOT/$NODE_DIST"
DSH_ROOT="$LOCAL_ROOT/dsh-runtime"
ARCHIVE_URL="https://nodejs.org/dist/v${NODE_VERSION}/${NODE_DIST}.tar.xz"

mkdir -p "$LOCAL_ROOT" "$BIN_DIR"
if [[ ! -x "$NODE_ROOT/bin/node" ]]; then
    archive="$(mktemp "${TMPDIR:-/tmp}/${NODE_DIST}.XXXXXX.tar.xz")"
    trap 'rm -f "$archive"' EXIT
    curl --fail --location --retry 3 --output "$archive" "$ARCHIVE_URL"
    tar -xJf "$archive" -C "$LOCAL_ROOT"
fi

export PATH="$NODE_ROOT/bin:$BIN_DIR:$PATH"
corepack enable
corepack prepare "pnpm@${PNPM_VERSION}" --activate

mkdir -p "$DSH_ROOT"
if [[ ! -f "$DSH_ROOT/package.json" ]]; then
    npm --prefix "$DSH_ROOT" init --yes >/dev/null
fi
pnpm --dir "$DSH_ROOT" add \
    --allow-build=@deepseek-ai/dsh-subprocess-local \
    --allow-build=@google/genai \
    --allow-build=koffi \
    --allow-build=node-pty \
    --allow-build=protobufjs \
    "@deepseek-ai/dsh@${DSH_VERSION}"

ln -sfn "$NODE_ROOT/bin/node" "$BIN_DIR/node"
ln -sfn "$NODE_ROOT/bin/npm" "$BIN_DIR/npm"
ln -sfn "$NODE_ROOT/bin/npx" "$BIN_DIR/npx"
ln -sfn "$NODE_ROOT/bin/corepack" "$BIN_DIR/corepack"
ln -sfn "$NODE_ROOT/bin/pnpm" "$BIN_DIR/pnpm"
if [[ -e "$NODE_ROOT/bin/pnpx" ]]; then
    ln -sfn "$NODE_ROOT/bin/pnpx" "$BIN_DIR/pnpx"
fi
DSH_ENTRY="$(find "$DSH_ROOT/node_modules/.pnpm" \
    -path '*/node_modules/@deepseek-ai/dsh/lib/bin.js' -print -quit)"
if [[ -z "$DSH_ENTRY" ]]; then
    echo "DeepSeek Harness entrypoint was not installed." >&2
    exit 2
fi
if [[ -L "$BIN_DIR/dsh" || -e "$BIN_DIR/dsh" ]]; then
    unlink "$BIN_DIR/dsh"
fi
cat >"$BIN_DIR/dsh" <<EOF
#!/usr/bin/env sh
exec "$NODE_ROOT/bin/node" "$DSH_ENTRY" "\$@"
EOF
chmod 0755 "$BIN_DIR/dsh"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PATH="$BIN_DIR:$NODE_ROOT/bin:$PATH" \
LIVEOPT_DSH_PROFILE="$PROFILE" \
LIVEOPT_DSH_BIN_DIR="$BIN_DIR" \
"$SCRIPT_DIR/install.sh"

"$BIN_DIR/dsh" --version
"$BIN_DIR/liveopt-mcp" --help >/dev/null
echo "Local LiveOpt + DeepSeek Harness installation is ready."
echo "Start with: $SCRIPT_DIR/start_local.sh"
