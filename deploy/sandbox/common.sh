#!/usr/bin/env bash
set -euo pipefail
P="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
set -a
source "$P/config.env"
set +a
R="$MAPLE_HOME"
export MAPLE_SANDBOX_ROOT="$P"
unset HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy
unset DEEPSEEK_API_KEY KIMI_API_KEY LIVEOPT_ENV_FILE PYTHONPATH
export PATH="$R/runtime/venv/bin:$R/bin:/usr/local/bin:/usr/bin:/bin"
