#!/usr/bin/env bash
set -euo pipefail
root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
[[ "$(uname -s)" == Linux ]] || { echo 'Use ./maple on macOS, or start.cmd on Windows.' >&2; exit 2; }
export MAPLE_HOME="${MAPLE_HOME:-$HOME/.local/share/maple-harness}"
tools="$MAPLE_HOME/bootstrap"
mkdir -p "$tools"
case "$(uname -m)" in
  x86_64) target=x86_64-unknown-linux-gnu; expected=e4f169ec380f1793b898a6f1fcbacd22db25cf7ca0349a6e96ffb85b69998d04 ;;
  aarch64|arm64) target=aarch64-unknown-linux-gnu; expected=611ff684f193a84d2fdad29c5f12505d02ece94984c7c982cdde950eba5c95b9 ;;
  *) echo 'Unsupported Linux architecture.' >&2; exit 2 ;;
esac
if [[ ! -x "$tools/uv" ]]; then
  echo '[1/5] Downloading the private Python installer...'
  archive="$(mktemp "${TMPDIR:-/tmp}/maple-uv.XXXXXX.tar.gz")"
  trap 'rm -f "$archive"' EXIT
  curl --fail --location --retry 2 --output "$archive" "https://github.com/astral-sh/uv/releases/download/0.13.3/uv-${target}.tar.gz"
  printf '%s  %s\n' "$expected" "$archive" | sha256sum --check --status
  tar -xzf "$archive" -C "$tools" --strip-components=1
fi
export UV_PYTHON_INSTALL_DIR="$MAPLE_HOME/python"
export UV_CACHE_DIR="$MAPLE_HOME/uv-cache"
echo '[1/5] Preparing Python (no administrator access required)...'
"$tools/uv" python install --no-bin --no-registry 3.13.15
python="$("$tools/uv" python find --managed-python 3.13.15)"
exec "$python" "$root/scripts/launcher.py" "$@"
