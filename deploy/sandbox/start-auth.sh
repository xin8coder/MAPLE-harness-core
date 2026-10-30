#!/usr/bin/env bash
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
set -a
source "$P/secrets/front.env"
set +a
exec "$R/runtime/venv/bin/python" -I "$P/app/auth.py"
