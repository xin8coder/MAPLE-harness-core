FROM node:22-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PNPM_HOME=/opt/pnpm \
    LIVEOPT_MCP_STATE_DIR=/data/liveopt \
    LIVEOPT_MCP_WORKSPACE_ROOT=/workspace \
    LIVEOPT_MCP_COMMAND=/opt/liveopt/bin/liveopt-mcp

ENV PATH="${PNPM_HOME}/bin:${PATH}"

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv python3-pip \
    && rm -rf /var/lib/apt/lists/* \
    && corepack enable \
    && corepack prepare pnpm@11.7.0 --activate \
    && mkdir -p "${PNPM_HOME}/bin" \
    && pnpm config set global-bin-dir "${PNPM_HOME}/bin" \
    && pnpm add --global \
       --allow-build=@deepseek-ai/dsh-subprocess-local \
       --allow-build=@google/genai \
       --allow-build=koffi \
       --allow-build=node-pty \
       --allow-build=protobufjs \
       @deepseek-ai/dsh@0.1.0-rc.8

COPY . /src/liveopt
RUN python3 -m venv /opt/liveopt \
    && /opt/liveopt/bin/pip install --no-cache-dir /src/liveopt \
       /src/liveopt/integrations/deepseek-harness-liveopt \
    && dsh plugin --profile web add /src/liveopt/integrations/deepseek-harness-liveopt/dsh-bundle

WORKDIR /workspace
VOLUME ["/data/liveopt", "/workspace"]
EXPOSE 3000

CMD ["dsh", "--profile", "web", "--host", "0.0.0.0", "--port", "3000", "--no-open"]
