#!/usr/bin/env bash
set -euo pipefail
source "$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)/common.sh"
PYTHON_BIN="${PYTHON_BIN:-python3}"
core_root="${LIVEOPT_CORE_ROOT:-$MAPLE_SOURCE_ROOT/vendor/liveopt-core}"
[[ -f "$core_root/pyproject.toml" ]] || { echo "The pinned MAPLE core is missing." >&2; exit 2; }
"$PYTHON_BIN" -c 'import sys; assert sys.version_info >= (3, 10), "Python 3.10 or newer is required"'
mkdir -p "$LIVEOPT_DSH_INSTALL_ROOT" "$LIVEOPT_DSH_BIN_DIR" "$LIVEOPT_MCP_WORKSPACE_ROOT"
"$PYTHON_BIN" -m venv "$LIVEOPT_DSH_INSTALL_ROOT/venv"
python="$LIVEOPT_DSH_INSTALL_ROOT/venv/bin/python"
"$python" -m pip install --upgrade pip
build_root="$(mktemp -d "${TMPDIR:-/tmp}/maple-dsh-install.XXXXXX")"
trap 'rm -rf "$build_root"' EXIT
mkdir -p "$build_root/core" "$build_root/plugin/src"
cp "$core_root/pyproject.toml" "$build_root/core/"
[[ ! -f "$core_root/MANIFEST.in" ]] || cp "$core_root/MANIFEST.in" "$build_root/core/"
cp -R "$core_root/evo2" "$core_root/demo" "$build_root/core/"
cp "$MAPLE_SOURCE_ROOT/pyproject.toml" "$build_root/plugin/"
cp -R "$MAPLE_SOURCE_ROOT/src/liveopt_dsh" "$build_root/plugin/src/"
"$python" -m pip wheel --no-deps --wheel-dir "$build_root/wheels" "$build_root/core" "$build_root/plugin"
"$python" -m pip install --force-reinstall --no-deps "$build_root"/wheels/*.whl
"$python" -m pip install "$build_root"/wheels/*.whl
mkdir -p "$LIVEOPT_DSH_INSTALL_ROOT/dsh-bundle"
cp -R "$MAPLE_SOURCE_ROOT/dsh-bundle/." "$LIVEOPT_DSH_INSTALL_ROOT/dsh-bundle/"
for command in liveopt-mcp liveopt-web-api liveopt-configure; do
  cat > "$LIVEOPT_DSH_BIN_DIR/$command" <<EOF
#!/usr/bin/env sh
exec "$LIVEOPT_DSH_INSTALL_ROOT/venv/bin/$command" "\$@"
EOF
  chmod 0755 "$LIVEOPT_DSH_BIN_DIR/$command"
done
dsh plugin --profile "$LIVEOPT_DSH_PROFILE" add "$LIVEOPT_DSH_INSTALL_ROOT/dsh-bundle"
"$LIVEOPT_DSH_BIN_DIR/liveopt-mcp" --help >/dev/null
cp "$MAPLE_SOURCE_ROOT/RELEASE_MANIFEST.json" "$LIVEOPT_DSH_INSTALL_ROOT/installed-manifest.json"
