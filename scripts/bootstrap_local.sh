#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"

case "$(uname -s)" in
  Linux) node_os=linux ;;
  Darwin) node_os=darwin ;;
  *) echo "Use the desktop client on Windows, or install the server under WSL." >&2; exit 2 ;;
esac
case "$(uname -m)" in
  x86_64) node_arch=x64 ;;
  aarch64|arm64) node_arch=arm64 ;;
  *) echo "Unsupported CPU architecture." >&2; exit 2 ;;
esac
command -v python3 >/dev/null || { echo "Install Python 3.10 or newer before starting MAPLE." >&2; exit 2; }
node_dist="node-v${NODE_VERSION}-${node_os}-${node_arch}"
node_root="$LIVEOPT_LOCAL_ROOT/$node_dist"
mkdir -p "$LIVEOPT_LOCAL_ROOT" "$LIVEOPT_DSH_BIN_DIR" "$LIVEOPT_MCP_WORKSPACE_ROOT"
if [[ ! -x "$node_root/bin/node" ]]; then
  archive="$(mktemp "${TMPDIR:-/tmp}/maple-node.XXXXXX.tar.gz")"
  trap 'rm -f "$archive" "$archive.sha256"' EXIT
  curl --fail --location --retry 2 --output "$archive" "https://nodejs.org/dist/v${NODE_VERSION}/${node_dist}.tar.gz"
  curl --fail --location --retry 2 --output "$archive.sha256" "https://nodejs.org/dist/v${NODE_VERSION}/SHASUMS256.txt"
  python3 - "$archive" "${node_dist}.tar.gz" <<'PY'
import hashlib
from pathlib import Path
import sys
archive, name = sys.argv[1:]
expected = dict(line.split()[::-1] for line in Path(archive + '.sha256').read_text().splitlines())
if hashlib.sha256(Path(archive).read_bytes()).hexdigest() != expected.get(name):
    raise SystemExit('Node.js archive checksum verification failed')
PY
  tar -xzf "$archive" -C "$LIVEOPT_LOCAL_ROOT"
fi
export PATH="$node_root/bin:$LIVEOPT_DSH_BIN_DIR:$PATH"
corepack enable
corepack prepare "pnpm@$PNPM_VERSION" --activate
dsh_root="$LIVEOPT_LOCAL_ROOT/dsh-runtime"
mkdir -p "$dsh_root"
cp "$MAPLE_SOURCE_ROOT/runtime/package.json" "$MAPLE_SOURCE_ROOT/runtime/pnpm-lock.yaml" "$MAPLE_SOURCE_ROOT/runtime/pnpm-workspace.yaml" "$dsh_root/"
pnpm --dir "$dsh_root" install --frozen-lockfile
for binary in node npm npx corepack pnpm; do
  ln -sfn "$node_root/bin/$binary" "$LIVEOPT_DSH_BIN_DIR/$binary"
done
cat > "$LIVEOPT_DSH_BIN_DIR/dsh" <<EOF
#!/usr/bin/env sh
exec "$node_root/bin/node" "$dsh_root/node_modules/@deepseek-ai/dsh/lib/bin.js" "\$@"
EOF
chmod 0755 "$LIVEOPT_DSH_BIN_DIR/dsh"
"$MAPLE_SOURCE_ROOT/scripts/install.sh"
echo "MAPLE is installed. Start it with: $MAPLE_SOURCE_ROOT/maple"
