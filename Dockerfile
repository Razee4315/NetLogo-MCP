# NetLogo-MCP — MCP server for NetLogo agent-based modeling (stdio transport).
#
# Default build bakes in NetLogo (headless) with its bundled JRE, so the
# image is fully functional out of the box:
#
#   docker build -t netlogo-mcp .
#   docker run -i --rm netlogo-mcp
#
# For a slim image without NetLogo (server starts and lists tools; model
# tools then require mounting a NetLogo installation at /opt/netlogo):
#
#   docker build --build-arg INSTALL_NETLOGO=false -t netlogo-mcp:slim .

FROM python:3.12-slim-bookworm

ARG NETLOGO_VERSION=7.0.4
ARG INSTALL_NETLOGO=true

LABEL org.opencontainers.image.title="NetLogo-MCP" \
      org.opencontainers.image.description="MCP server for NetLogo — create, run, and analyze agent-based models" \
      org.opencontainers.image.source="https://github.com/Razee4315/NetLogo-MCP" \
      org.opencontainers.image.licenses="MIT"

# Headless AWT still needs font and X client libraries (export_view renders
# the world to PNG without a display).
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fontconfig \
        libfreetype6 \
        libxext6 \
        libxi6 \
        libxrender1 \
        libxtst6 \
    && rm -rf /var/lib/apt/lists/*

# NetLogo ships a matching JRE under runtime/ — no separate JDK needed.
# JPype finds libjvm.so via JAVA_HOME (see src/netlogo_mcp/config.py).
RUN if [ "$INSTALL_NETLOGO" = "true" ]; then \
        curl -fL --retry 5 --retry-all-errors --speed-limit 10240 --speed-time 60 \
            "https://github.com/NetLogo/NetLogo/releases/download/v${NETLOGO_VERSION}/NetLogo-${NETLOGO_VERSION}-64.tgz" \
            -o /tmp/netlogo.tgz \
        && mkdir -p /opt/netlogo \
        && tar -xzf /tmp/netlogo.tgz -C /opt/netlogo --strip-components=1 \
        && rm /tmp/netlogo.tgz; \
    fi

ENV NETLOGO_HOME=/opt/netlogo \
    JAVA_HOME=/opt/netlogo/lib/runtime \
    NETLOGO_GUI=false \
    NETLOGO_MODELS_DIR=/data/models \
    NETLOGO_EXPORTS_DIR=/data/exports

RUN mkdir -p /data/models /data/exports

WORKDIR /app
COPY pyproject.toml README.md LICENSE ./
COPY src/ src/
RUN pip install --no-cache-dir .

# MCP stdio transport: JSON-RPC over stdin/stdout.
ENTRYPOINT ["netlogo-mcp"]
