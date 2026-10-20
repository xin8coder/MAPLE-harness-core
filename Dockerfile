FROM node:24.19.0-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends python3 python3-venv curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*
ENV MAPLE_HOME=/opt/maple \
    DSH_HOME=/data/maple/dsh-home \
    LIVEOPT_MCP_STATE_DIR=/data/maple/state \
    LIVEOPT_MCP_WORKSPACE_ROOT=/workspace \
    LIVEOPT_DSH_HOST=0.0.0.0 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
COPY . /opt/maple-source
RUN /opt/maple-source/scripts/bootstrap_local.sh
WORKDIR /workspace
VOLUME ["/data/maple", "/workspace"]
EXPOSE 3000
CMD ["/opt/maple-source/maple"]
