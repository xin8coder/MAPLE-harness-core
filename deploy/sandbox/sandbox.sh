#!/usr/bin/env bash
# Run the public MAPLE Harness inside an isolated bubblewrap sandbox.
#
# Inside: no network except loopback, no host home directories, only the
# application runtime (read-only) and this instance's own data directory.
# Model calls leave through run/llm/llm.sock (host proxy that adds the real
# key and only reaches DeepSeek); browser traffic enters through run/web/web.sock.
source "$(dirname -- "${BASH_SOURCE[0]}")/common.sh"
D=$P/data
LLM_PORT=$MAPLE_MODEL_PORT
WEB_PORT=$MAPLE_WEB_PORT
API_PORT=$MAPLE_API_PORT

mkdir -p "$P/run/llm" "$P/run/web" "$D/dsh-home" "$D/state" "$D/home" "$D/workspace"

runtime=()
for d in "$R"/node-v*-linux-* "$R/runtime" "$R/dsh-runtime" "$R/python" "$R/corepack" "$R/bin"; do
    [[ ! -d "$d" ]] || runtime+=(--ro-bind "$d" "$d")
done

etc=()
for f in ld.so.cache ld.so.conf ld.so.conf.d alternatives ssl ca-certificates localtime timezone nsswitch.conf mime.types; do
    [[ -e /etc/$f ]] && etc+=(--ro-bind "/etc/$f" "/etc/$f")
done

# With arguments, run that command under the same isolation (used for probes).
if [[ $# -gt 0 ]]; then
    cmd=("$@")
else
    cmd=(/bin/bash /opt/maple-sandbox/inside.sh)
fi

# No cgroup delegation here: cap threads and single-file size with rlimits.
ulimit -u 15000
ulimit -f 4194304

exec env -i PATH=/usr/bin:/bin /usr/bin/bwrap \
    --unshare-all --die-with-parent --new-session --cap-drop ALL \
    --hostname maple --uid "$(id -u)" --gid "$(id -g)" \
    --ro-bind /usr /usr \
    --symlink usr/bin /bin --symlink usr/lib /lib --symlink usr/lib64 /lib64 --symlink usr/sbin /sbin \
    "${etc[@]}" \
    --ro-bind "$P/conf/passwd" /etc/passwd \
    --ro-bind "$P/conf/group" /etc/group \
    --ro-bind "$P/conf/hosts" /etc/hosts \
    --proc /proc --dev /dev \
    --tmpfs /tmp --tmpfs /var/tmp --tmpfs /run --tmpfs /home \
    "${runtime[@]}" \
    --ro-bind "$P/app/runtime" /opt/maple-sandbox \
    --bind "$D" /data \
    --ro-bind "$P/run/llm" /run/maple/llm \
    --bind "$P/run/web" /run/maple/web \
    --chdir /data/workspace \
    --setenv HOME /data/home \
    --setenv USER maple \
    --setenv LANG C.UTF-8 \
    --setenv TZ "${TZ:-UTC}" \
    --setenv PATH "$R/runtime/venv/bin:$R/bin:/usr/bin:/bin" \
    --setenv XDG_CACHE_HOME /data/home/.cache \
    --setenv PYTHONSAFEPATH 1 \
    --setenv MAPLE_HOME "$R" \
    --setenv LIVEOPT_LOCAL_ROOT /data/local \
    --setenv LIVEOPT_DSH_INSTALL_ROOT "$R/runtime" \
    --setenv LIVEOPT_DSH_BIN_DIR "$R/bin" \
    --setenv COREPACK_HOME "$R/corepack" \
    --setenv DSH_HOME /data/dsh-home \
    --setenv LIVEOPT_MCP_STATE_DIR /data/state \
    --setenv LIVEOPT_MCP_WORKSPACE_ROOT /data/workspace \
    --setenv LIVEOPT_MCP_COMMAND "$R/runtime/venv/bin/liveopt-mcp" \
    --setenv LIVEOPT_WEB_API_URL "http://127.0.0.1:$API_PORT" \
    --setenv LIVEOPT_MCP_NETWORK_MODE direct \
    --setenv LIVEOPT_MCP_DEFAULT_MODEL deepseek-flash \
    --setenv LIVEOPT_MCP_MAX_WORKERS 2 \
    --setenv DEEPSEEK_MODEL deepseek-flash \
    --setenv DEEPSEEK_BASE_URL "http://127.0.0.1:$LLM_PORT" \
    --setenv DEEPSEEK_API_KEY sk-sandbox-placeholder \
    --setenv NODE_USE_ENV_PROXY 0 \
    --setenv MAPLE_MODEL_PORT "$LLM_PORT" \
    --setenv MAPLE_WEB_PORT "$WEB_PORT" \
    --setenv MAPLE_API_PORT "$API_PORT" \
    --setenv DSH_TELEMETRY_DISABLED 1 \
    --setenv LIVEOPT_DSH_HOST 127.0.0.1 \
    --setenv MAPLE_PORT "$WEB_PORT" \
    --setenv LIVEOPT_WEB_API_PORT "$API_PORT" \
    "${cmd[@]}"
