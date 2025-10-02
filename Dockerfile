# ---------- base: tools + deps ----------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates openjdk-17-jre-headless unzip \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /opt/app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project

# Use a real asset from the v0.9.7 release (zip, not tgz)
ARG DEPENDS_ZIP="depends-0.9.7-package-20221030.zip"
ARG DEPENDS_URL="https://github.com/multilang-depends/depends/releases/download/v0.9.7/${DEPENDS_ZIP}"

# Download + extract
RUN curl -fsSL -o /tmp/depends.zip "$DEPENDS_URL" \
 && mkdir -p /opt/depends \
 && unzip -q /tmp/depends.zip -d /opt/depends \
 && rm /tmp/depends.zip \
 # Flatten any one nested top-level directory
 && sh -lc 'd=$(find /opt/depends -mindepth 1 -maxdepth 1 -type d | head -n1); \
            if [ -n "$d" ] && [ "$d" != "/opt/depends/bin" ]; then \
              mv "$d"/* /opt/depends/ && rmdir "$d"; \
            fi'
ENV PATH="/opt/depends/bin:/opt/depends:/opt/app/.venv/bin:${PATH}"


# Fallback wrapper (runs the JAR if no launcher is present)
RUN printf '%s\n' '#!/usr/bin/env bash' \
                  'set -euo pipefail' \
                  'if command -v depends >/dev/null 2>&1; then exec depends "$@"; fi' \
                  'exec java -jar /opt/depends/depends*.jar "$@"' \
    > /usr/local/bin/depends-cli && chmod +x /usr/local/bin/depends-cli

ENV PATH="/opt/depends/bin:/opt/depends:/opt/app/.venv/bin:${PATH}"

# ---------- dev: mount code at runtime (no COPY) ----------
FROM base AS dev
WORKDIR /workspace
# Auto-activate the uv virtualenv for interactive shells
RUN printf 'source /opt/app/.venv/bin/activate\n' >> /root/.bashrc
CMD ["bash", "-l"]

# ---------- prod: copy code into image ----------
FROM base AS prod
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked   # installs your project into the venv
# I must change this to be the actual entry point of my code later
CMD ["python", "cycle_extractor/compute_global_metrics.py"]
