# ---------- base: tools + deps (dev-only) ----------
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS dev

# add docker CLI so OpenHands can talk to /var/run/docker.sock
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl ca-certificates openjdk-17-jre-headless unzip git \
    docker.io rsync \
 && rm -rf /var/lib/apt/lists/*

# ---- install .NET SDKs ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    wget gnupg \
 && wget -qO- https://packages.microsoft.com/keys/microsoft.asc | gpg --dearmor > /etc/apt/trusted.gpg.d/microsoft.gpg \
 && . /etc/os-release && wget -q https://packages.microsoft.com/config/debian/$VERSION_ID/packages-microsoft-prod.deb \
 && dpkg -i packages-microsoft-prod.deb \
 && rm packages-microsoft-prod.deb \
 && apt-get update && apt-get install -y --no-install-recommends \
    dotnet-sdk-6.0 \
    dotnet-sdk-8.0 \
    dotnet-sdk-9.0 \
    dotnet-sdk-10.0 \
 && rm -rf /var/lib/apt/lists/*

ENV NUGET_PACKAGES=/opt/nuget/packages
RUN mkdir -p /opt/nuget/packages && chmod -R 0777 /opt/nuget

# Mono (needed for running .NET Framework tests like net48 via dotnet test)
RUN apt-get update && apt-get install -y --no-install-recommends \
    mono-runtime \
    ca-certificates-mono \
 && rm -rf /var/lib/apt/lists/*

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    pkg-config \
    libffi-dev \
    libssl-dev \
    libnss-wrapper \
 && rm -rf /var/lib/apt/lists/*

# ----- R + lme4 (GLMM) -----
RUN apt-get update && apt-get install -y --no-install-recommends \
    r-base \
    r-base-dev \
    r-cran-lme4 \
    r-cran-readr \
    r-cran-dplyr \
    r-cran-broom \
 && rm -rf /var/lib/apt/lists/*

# ----- your existing Python deps via uv -----
WORKDIR /opt/app
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-install-project

# Ensure PATH contains your venv
ENV PATH="/opt/app/.venv/bin:${PATH}"

# ----- your existing "depends" tool setup -----
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

# auto-activate the uv virtualenv in interactive shells (all users)
RUN printf '\n# Auto-activate project venv\nsource /opt/app/.venv/bin/activate\n' >> /etc/bash.bashrc

# optional but nice: make sure non-root users have a writable HOME
ENV HOME=/tmp

CMD ["bash", "-l"]