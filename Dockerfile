# ---------- base: tools + deps (dev-only) ----------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS dev

# add docker CLI so OpenHands can talk to /var/run/docker.sock
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates openjdk-17-jre-headless unzip git \
    docker.io \
 && rm -rf /var/lib/apt/lists/*

# ----- your existing Python deps via uv (OpenHands must be in uv.lock) -----
WORKDIR /opt/app
COPY pyproject.toml uv.lock ./
# make sure you've done: `uv add openhands` locally before building
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project

# ----- your existing "depends" tool setup (unchanged) -----
ARG DEPENDS_ZIP="depends-0.9.7-package-20221030.zip"
ARG DEPENDS_URL="https://github.com/multilang-depends/depends/releases/download/v0.9.7/${DEPENDS_ZIP}"
RUN curl -fsSL -o /tmp/depends.zip "$DEPENDS_URL" \
 && mkdir -p /opt/depends \
 && unzip -q /tmp/depends.zip -d /opt/depends \
 && rm /tmp/depends.zip \
 && sh -lc 'd=$(find /opt/depends -mindepth 1 -maxdepth 1 -type d | head -n1); \
            if [ -n "$d" ] && [ "$d" != "/opt/depends/bin" ]; then \
              mv "$d"/* /opt/depends/ && rmdir "$d"; \
            fi'

# fallback wrapper
RUN printf '%s\n' '#!/usr/bin/env bash' \
                  'set -euo pipefail' \
                  'if command -v depends >/dev/null 2>&1; then exec depends "$@"; fi' \
                  'exec java -jar /opt/depends/depends*.jar "$@"' \
    > /usr/local/bin/depends-cli && chmod +x /usr/local/bin/depends-cli

# PATHs (uv venv + depends)
ENV PATH="/opt/depends/bin:/opt/depends:/opt/app/.venv/bin:${PATH}"

# ----- dev shell -----
WORKDIR /workspace
# auto-activate the uv virtualenv in interactive shells
RUN printf 'source /opt/app/.venv/bin/activate\n' >> /root/.bashrc
CMD ["bash", "-l"]
