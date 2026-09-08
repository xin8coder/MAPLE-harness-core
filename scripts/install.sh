#!/usr/bin/env bash
set -euo pipefail

PROFILE="${LIVEOPT_DSH_PROFILE:-web}"
INSTALL_ROOT="${LIVEOPT_DSH_INSTALL_ROOT:-$HOME/.local/share/liveopt-dsh/runtime}"
BIN_DIR="${LIVEOPT_DSH_BIN_DIR:-$HOME/.local/bin}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
PLUGIN_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
MONOREPO_ROOT="$(cd -- "$PLUGIN_ROOT/../.." && pwd)"
if [[ -n "${LIVEOPT_CORE_ROOT:-}" ]]; then
    CORE_ROOT="$(cd -- "$LIVEOPT_CORE_ROOT" && pwd)"
elif [[ -f "$PLUGIN_ROOT/vendor/liveopt-core/pyproject.toml" && -d "$PLUGIN_ROOT/vendor/liveopt-core/evo2" ]]; then
    CORE_ROOT="$PLUGIN_ROOT/vendor/liveopt-core"
elif [[ -f "$MONOREPO_ROOT/pyproject.toml" && -d "$MONOREPO_ROOT/evo2" ]]; then
    CORE_ROOT="$MONOREPO_ROOT"
else
    echo "LiveOpt core source was not found." >&2
    echo "Set LIVEOPT_CORE_ROOT or use the standalone release with vendor/liveopt-core." >&2
    exit 2
fi
BUILD_ROOT="$(mktemp -d "${TMPDIR:-/tmp}/liveopt-dsh-install.XXXXXX")"

cleanup() {
    rm -rf "$BUILD_ROOT"
}
trap cleanup EXIT

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("LiveOpt requires Python 3.10 or newer")
PY

mkdir -p "$INSTALL_ROOT" "$BIN_DIR"
"$PYTHON_BIN" -m venv "$INSTALL_ROOT/venv"
"$INSTALL_ROOT/venv/bin/python" -m pip install --upgrade pip

# Build from disposable source snapshots. This keeps setuptools metadata and
# wheel build products out of the paper checkout.
mkdir -p "$BUILD_ROOT/core" "$BUILD_ROOT/plugin/src" "$BUILD_ROOT/wheels"
cp "$CORE_ROOT/pyproject.toml" "$BUILD_ROOT/core/pyproject.toml"
cp -R "$CORE_ROOT/evo2" "$CORE_ROOT/demo" "$BUILD_ROOT/core/"
cp "$PLUGIN_ROOT/pyproject.toml" "$BUILD_ROOT/plugin/pyproject.toml"
cp -R "$PLUGIN_ROOT/src/liveopt_dsh" "$BUILD_ROOT/plugin/src/"
cp -R "$PLUGIN_ROOT/dsh-bundle" "$BUILD_ROOT/dsh-bundle"

"$INSTALL_ROOT/venv/bin/python" -m pip wheel --no-deps \
    --wheel-dir "$BUILD_ROOT/wheels" \
    "$BUILD_ROOT/core" "$BUILD_ROOT/plugin"
CORE_WHEEL=("$BUILD_ROOT"/wheels/liveopt-0.1.0-*.whl)
PLUGIN_WHEEL=("$BUILD_ROOT"/wheels/liveopt_dsh_sidecar-0.1.0-*.whl)
"$INSTALL_ROOT/venv/bin/python" -m pip install "${CORE_WHEEL[0]}"
"$INSTALL_ROOT/venv/bin/python" -m pip install "${PLUGIN_WHEEL[0]}"
"$INSTALL_ROOT/venv/bin/python" -m pip install --force-reinstall --no-deps \
    "${CORE_WHEEL[0]}" "${PLUGIN_WHEEL[0]}"
mkdir -p "$INSTALL_ROOT/dsh-bundle"
cp -R "$BUILD_ROOT/dsh-bundle/." "$INSTALL_ROOT/dsh-bundle/"

cat >"$BIN_DIR/liveopt-mcp" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_ROOT/venv/bin/liveopt-mcp" "\$@"
EOF
chmod 0755 "$BIN_DIR/liveopt-mcp"

cat >"$BIN_DIR/liveopt-web-api" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_ROOT/venv/bin/liveopt-web-api" "\$@"
EOF
chmod 0755 "$BIN_DIR/liveopt-web-api"

cat >"$BIN_DIR/liveopt-configure" <<EOF
#!/usr/bin/env sh
exec "$INSTALL_ROOT/venv/bin/liveopt-configure" "\$@"
EOF
chmod 0755 "$BIN_DIR/liveopt-configure"

if command -v dsh >/dev/null 2>&1; then
    DSH=(dsh)
elif command -v npx >/dev/null 2>&1; then
    DSH=(npx -y @deepseek-ai/dsh@0.1.0-rc.8)
else
    echo "Python sidecar installed, but Node.js/dsh is unavailable." >&2
    echo "Install Node.js 22.19+ and run: dsh plugin --profile $PROFILE add $PLUGIN_ROOT/dsh-bundle" >&2
    exit 2
fi

"${DSH[@]}" plugin --profile "$PROFILE" add "$INSTALL_ROOT/dsh-bundle"

# Replace the upstream browser-shell identity before the application starts.
# Runtime branding in client.js repeats this after hydration, while these
# static edits prevent the browser tab and PWA manifest from briefly exposing
# the host product name.
LOCAL_ROOT="${LIVEOPT_LOCAL_ROOT:-$HOME/.local/share/liveopt-dsh}"
for web_root in "$LOCAL_ROOT"/dsh-runtime/node_modules/.pnpm/@deepseek-ai+dsh-web-frontend@*/node_modules/@deepseek-ai/dsh-web-frontend/dist; do
    [[ -d "$web_root" ]] || continue
    "$PYTHON_BIN" - "$web_root" <<'PY'
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
index = root / "index.html"
if index.exists():
    text = index.read_text(encoding="utf-8")
    text = text.replace("<title>DeepSeek Harness</title>", "<title>LiveOpt Harness</title>")
    index.write_text(text, encoding="utf-8")

manifest = root / "manifest.webmanifest"
if manifest.exists():
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["name"] = "LiveOpt Harness"
    payload["short_name"] = "LiveOpt"
    manifest.write_text(json.dumps(payload, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
PY
done

for renderer in "$LOCAL_ROOT"/dsh-runtime/node_modules/.pnpm/@deepseek-ai+dsh-client-ui-renderer@*/node_modules/@deepseek-ai/dsh-client-ui-renderer/lib/client.js; do
    [[ -f "$renderer" ]] || continue
    "$PYTHON_BIN" - "$renderer" <<'PY'
import sys
from pathlib import Path

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
text = text.replace(
    'const productTitle = "DeepSeek Harness";',
    'const productTitle = "LiveOpt Harness";',
)
path.write_text(text, encoding="utf-8")
PY
done

echo "LiveOpt sidecar: $BIN_DIR/liveopt-mcp"
echo "DSH profile: $PROFILE"
echo "Start with: ${DSH[*]} --profile $PROFILE"
