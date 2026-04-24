FROM nikolaik/python-nodejs:python3.11-nodejs24-slim

ARG OPENAI_CODEX_CLI_VERSION=0.124.0
LABEL ii_agent.sandbox_provider="daytona"
LABEL ii_agent.codex_cli_package="@openai/codex@${OPENAI_CODEX_CLI_VERSION}"

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
  --mount=type=cache,target=/var/lib/apt,sharing=locked \
  apt-get update && apt-get install -y \
  bash \
  ca-certificates \
  curl \
  git \
  procps \
  ripgrep \
  tmux \
  && rm -rf /var/lib/apt/lists/*

RUN --mount=type=cache,target=/root/.npm \
  npm install -g @openai/codex@${OPENAI_CODEX_CLI_VERSION}

RUN if ! id -u user >/dev/null 2>&1; then \
    useradd -d /home/user -m -s /bin/bash user; \
  fi && \
  mkdir -p /workspace /home/user/.codex && \
  chown -R user:user /workspace /home/user

ENV HOME=/home/user
WORKDIR /workspace

USER user
CMD ["bash", "-lc", "sleep infinity"]
