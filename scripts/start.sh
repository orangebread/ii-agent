#!/usr/bin/env bash

if [ -z "${BASH_VERSION:-}" ] || [ "${BASH##*/}" = "sh" ]; then
  if command -v bash >/dev/null 2>&1; then
    exec bash "$0" "$@"
  fi
  printf '%s\n' "scripts/start.sh requires bash, but 'bash' was not found on PATH." >&2
  exit 1
fi

set -uo pipefail

SCRIPT_DIR=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
ENV_FILE="${II_AGENT_ENV_FILE:-$REPO_ROOT/.env}"
ENV_EXAMPLE_FILE="${II_AGENT_ENV_EXAMPLE_FILE:-$REPO_ROOT/.env.example}"
FRONTEND_DIR="${II_AGENT_FRONTEND_DIR:-$REPO_ROOT/frontend}"
FRONTEND_ENV_FILE="${II_AGENT_FRONTEND_ENV_FILE:-$FRONTEND_DIR/.env}"
FRONTEND_ENV_EXAMPLE_FILE="${II_AGENT_FRONTEND_ENV_EXAMPLE_FILE:-$FRONTEND_DIR/.env.example}"
COMPOSE_DEV_FILE="${II_AGENT_COMPOSE_DEV_FILE:-$REPO_ROOT/docker/docker-compose.dev.yaml}"
COMPOSE_PROJECT_NAME="${DEV_PROJECT_NAME:-ii-agent-dev}"
PREFLIGHT_HELPER="$REPO_ROOT/scripts/start_preflight.py"
DAYTONA_CACHE_DIR="${II_AGENT_DAYTONA_CACHE_DIR:-$REPO_ROOT/.cache/ii-agent-daytona}"
DAYTONA_REPO_URL="${II_AGENT_DAYTONA_REPO_URL:-https://github.com/daytonaio/daytona.git}"
DAYTONA_REPO_REF="${II_AGENT_DAYTONA_REPO_REF:-main}"
DAYTONA_REPO_DIR="${II_AGENT_DAYTONA_REPO_DIR:-$DAYTONA_CACHE_DIR/daytona}"
DAYTONA_COMPOSE_PROJECT_NAME="${II_AGENT_DAYTONA_COMPOSE_PROJECT_NAME:-ii-agent-daytona}"
DAYTONA_COMPOSE_FILE="$DAYTONA_REPO_DIR/docker/docker-compose.ii-agent.yaml"
DAYTONA_COMPOSE_ATTEMPTS="${II_AGENT_DAYTONA_COMPOSE_ATTEMPTS:-3}"
DAYTONA_COMPOSE_PARALLEL_LIMIT="${II_AGENT_DAYTONA_COMPOSE_PARALLEL_LIMIT:-1}"
DAYTONA_OUTER_NETWORK_SUBNET="${II_AGENT_DAYTONA_OUTER_NETWORK_SUBNET:-172.31.0.0/16}"
DAYTONA_AUTO_BUILD_SANDBOX_IMAGE="${II_AGENT_DAYTONA_AUTO_BUILD_SANDBOX_IMAGE:-1}"
DAYTONA_SANDBOX_DOCKERFILE="${II_AGENT_DAYTONA_SANDBOX_DOCKERFILE:-$REPO_ROOT/docker/sandbox/daytona.Dockerfile}"
DAYTONA_LOCAL_SANDBOX_IMAGE_REPOSITORY="${II_AGENT_DAYTONA_LOCAL_SANDBOX_IMAGE_REPOSITORY:-ii-agent-codex-sandbox}"
DAYTONA_LOCAL_SANDBOX_IMAGE_TAG="${II_AGENT_DAYTONA_LOCAL_SANDBOX_IMAGE_TAG:-daytona-amd64}"

CHECK_ONLY=0
AUTO_HEAL=1
XVFB_PID=""
BACKEND_PID=""
FRONTEND_PID=""
SERVICES_STARTED=0
SERVER_ARGS=()
SERVER_HOST="0.0.0.0"
SERVER_PORT="${PORT:-8000}"
PORT_SET=0
BACKEND_ONLY=0
FRONTEND_HOST="0.0.0.0"
FRONTEND_PORT=1420

FAILURES=()
WARNINGS=()
REPAIRS=()
DAYTONA_RESERVED_PORTS=()

RUNTIME_ENVIRONMENT=""
RUNTIME_DATABASE_URL=""
RUNTIME_DATABASE_IS_LOCAL=0
RUNTIME_REDIS_ENABLED=0
RUNTIME_REDIS_URL=""
RUNTIME_REDIS_IS_LOCAL=0
RUNTIME_STORAGE_PROVIDER=""
RUNTIME_STORAGE_LOCAL_DIR=""
RUNTIME_STORAGE_MINIO_ENDPOINT=""
RUNTIME_STORAGE_MINIO_IS_LOCAL=0
RUNTIME_STORAGE_GCS_BUCKET=""
RUNTIME_STORAGE_GCS_PROJECT=""
RUNTIME_MODEL_CONFIGS_PRESENT=0
RUNTIME_SANDBOX_PROVIDER=""
RUNTIME_SANDBOX_DOCKER_IMAGE=""
RUNTIME_SANDBOX_DAYTONA_API_URL=""
RUNTIME_SANDBOX_DAYTONA_API_KEY_PRESENT=0
RUNTIME_SANDBOX_DAYTONA_DEFAULT_IMAGE=""
RUNTIME_SANDBOX_CODEX_CLI_PACKAGE=""
RUNTIME_SANDBOX_READY=1
RUNTIME_CODEX_APP_SERVER_WORKFLOWS_ENABLED=1
RUNTIME_CODEX_APP_SERVER_SMOKE_VERIFIED=0

log() {
  printf '%s\n' "$*"
}

info() {
  printf '[INFO] %s\n' "$*"
}

ok() {
  printf '[ OK ] %s\n' "$*"
}

warn() {
  WARNINGS+=("$*")
  printf '[WARN] %s\n' "$*"
}

repair() {
  REPAIRS+=("$*")
  printf '[FIX ] %s\n' "$*"
}

fail() {
  FAILURES+=("$*")
  printf '[FAIL] %s\n' "$*" >&2
}

has_failure_matching() {
  local pattern="$1"
  local item
  for item in "${FAILURES[@]}"; do
    if [[ "$item" == *"$pattern"* ]]; then
      return 0
    fi
  done
  return 1
}

cleanup() {
  if [[ -n "$BACKEND_PID" ]] && kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
    kill "$BACKEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$FRONTEND_PID" ]] && kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
    kill "$FRONTEND_PID" >/dev/null 2>&1 || true
  fi
  if [[ -n "$XVFB_PID" ]] && kill -0 "$XVFB_PID" >/dev/null 2>&1; then
    kill "$XVFB_PID" >/dev/null 2>&1 || true
  fi
  if [[ $SERVICES_STARTED -eq 1 ]]; then
    cleanup_local_sandbox_containers "shutdown"
  fi
}

trap cleanup EXIT

usage() {
  printf '%s\n' \
    "Usage: ./scripts/start.sh [--check-only] [--no-heal] [--host HOST] [PORT] [uvicorn args...]" \
    "" \
    "Options:" \
    "  --check-only   Run the full preflight and exit without starting the server." \
    "  --no-heal      Disable self-healing behavior (no auto copy, sync, or docker infra start)." \
    "  --backend-only Start only the backend service." \
    "  --host HOST    Host passed to ii_agent.ws_server." \
    "" \
    "Behavior:" \
    "  - Copies .env from .env.example if missing." \
    "  - Copies frontend/.env from frontend/.env.example if missing." \
    "  - Repairs the Python environment with \`uv sync --frozen\` when needed." \
    "  - Repairs the frontend environment with \`npm install\` when needed." \
    "  - Starts local Docker infra when configured services point at localhost and are unavailable." \
    "  - Starts a local Daytona OSS stack when SANDBOX_PROVIDER=daytona points at localhost and is unavailable." \
    "  - Runs blocking validations before launching backend + frontend local services."
}

parse_args() {
  while (($#)); do
    case "$1" in
      --check-only)
        CHECK_ONLY=1
        shift
        ;;
      --no-heal)
        AUTO_HEAL=0
        shift
        ;;
      --backend-only)
        BACKEND_ONLY=1
        shift
        ;;
      --host)
        if (($# < 2)); then
          fail "--host requires a value"
          return 1
        fi
        SERVER_HOST="$2"
        SERVER_ARGS+=("--host" "$2")
        shift 2
        ;;
      --help|-h)
        usage
        exit 0
        ;;
      --)
        shift
        while (($#)); do
          SERVER_ARGS+=("$1")
          shift
        done
        ;;
      *)
        if [[ $PORT_SET -eq 0 && "$1" =~ ^[0-9]+$ ]]; then
          SERVER_PORT="$1"
          PORT_SET=1
          shift
          continue
        fi
        SERVER_ARGS+=("$1")
        shift
        ;;
    esac
  done

  if [[ $PORT_SET -eq 1 ]]; then
    SERVER_ARGS=("--port" "$SERVER_PORT" "${SERVER_ARGS[@]}")
  elif [[ -n "${PORT:-}" ]]; then
    SERVER_ARGS=("--port" "$SERVER_PORT" "${SERVER_ARGS[@]}")
  fi

  local next_is_port=0
  local next_is_host=0
  local arg
  for arg in "${SERVER_ARGS[@]}"; do
    if [[ $next_is_port -eq 1 ]]; then
      SERVER_PORT="$arg"
      next_is_port=0
      continue
    fi
    if [[ $next_is_host -eq 1 ]]; then
      SERVER_HOST="$arg"
      next_is_host=0
      continue
    fi
    case "$arg" in
      --port)
        next_is_port=1
        ;;
      --host)
        next_is_host=1
        ;;
    esac
  done

  if [[ ! "$SERVER_PORT" =~ ^[0-9]+$ ]]; then
    fail "Server port must be numeric, got: $SERVER_PORT"
    return 1
  fi
}

ensure_env_file() {
  if [[ -f "$ENV_FILE" ]]; then
    ok "Using existing .env"
    return 0
  fi

  if [[ ! -f "$ENV_EXAMPLE_FILE" ]]; then
    fail "Missing .env and no .env.example template is available"
    return 1
  fi

  if [[ $AUTO_HEAL -ne 1 ]]; then
    fail "Missing .env; rerun without --no-heal to create it from .env.example"
    return 1
  fi

  cp "$ENV_EXAMPLE_FILE" "$ENV_FILE"
  repair "Created .env from .env.example"
}

ensure_frontend_env_file() {
  if [[ $BACKEND_ONLY -eq 1 ]]; then
    return 0
  fi

  if [[ -f "$FRONTEND_ENV_FILE" ]]; then
    ok "Using existing frontend/.env"
    return 0
  fi

  if [[ ! -f "$FRONTEND_ENV_EXAMPLE_FILE" ]]; then
    fail "Missing frontend/.env and no frontend/.env.example template is available"
    return 1
  fi

  if [[ $AUTO_HEAL -ne 1 ]]; then
    fail "Missing frontend/.env; rerun without --no-heal to create it from frontend/.env.example"
    return 1
  fi

  cp "$FRONTEND_ENV_EXAMPLE_FILE" "$FRONTEND_ENV_FILE"
  repair "Created frontend/.env from frontend/.env.example"
}

load_env_file() {
  local override_names=(
    SANDBOX_PROVIDER
    SANDBOX_DAYTONA_API_URL
    SANDBOX_DAYTONA_API_KEY
    SANDBOX_DAYTONA_TARGET
    SANDBOX_DAYTONA_DEFAULT_IMAGE
    SANDBOX_DAYTONA_SNAPSHOT
    SANDBOX_DAYTONA_AUTO_STOP_INTERVAL
    SANDBOX_DAYTONA_EPHEMERAL
    SANDBOX_DAYTONA_PUBLIC_PREVIEW
    SANDBOX_DAYTONA_NETWORK_BLOCK_ALL
    SANDBOX_DAYTONA_NETWORK_ALLOW_LIST
    CODEX_APP_SERVER_WORKFLOWS_ENABLED
    CODEX_APP_SERVER_SMOKE_VERIFIED
  )
  local override_sets=()
  local override_values=()
  local var_name
  for var_name in "${override_names[@]}"; do
    if [[ -n "${!var_name+x}" ]]; then
      override_sets+=(1)
      override_values+=("${!var_name}")
    else
      override_sets+=(0)
      override_values+=("")
    fi
  done

  set -a
  # shellcheck disable=SC1090
  if . "$ENV_FILE"; then
    set +a
    local i
    for ((i = 0; i < ${#override_names[@]}; i += 1)); do
      if [[ "${override_sets[$i]}" -eq 1 ]]; then
        printf -v "${override_names[$i]}" '%s' "${override_values[$i]}"
        export "${override_names[$i]}"
      fi
    done
    ok "Loaded environment from $ENV_FILE"
    return 0
  fi
  set +a
  fail "Failed to load environment file: $ENV_FILE"
  return 1
}

load_frontend_env_file() {
  if [[ $BACKEND_ONLY -eq 1 ]]; then
    return 0
  fi

  set -a
  # shellcheck disable=SC1090
  if . "$FRONTEND_ENV_FILE"; then
    set +a
    FRONTEND_PORT="${VITE_PORT:-$FRONTEND_PORT}"
    ok "Loaded frontend environment from $FRONTEND_ENV_FILE"
    return 0
  fi
  set +a
  fail "Failed to load frontend environment file: $FRONTEND_ENV_FILE"
  return 1
}

ensure_command() {
  local command_name="$1"
  local hint="$2"
  if command -v "$command_name" >/dev/null 2>&1; then
    ok "Found required command: $command_name"
    return 0
  fi
  fail "Missing required command: $command_name. $hint"
  return 1
}

ensure_uv_environment() {
  if uv run python -c "import ii_agent" >/dev/null 2>&1; then
    ok "Python dependencies are available through uv"
    return 0
  fi

  if [[ $AUTO_HEAL -ne 1 ]]; then
    fail "Python environment is not ready; run 'uv sync --frozen' or rerun without --no-heal"
    return 1
  fi

  info "Python environment is incomplete; running uv sync --frozen"
  if uv sync --frozen; then
    repair "Synchronized Python dependencies with uv"
  else
    fail "uv sync --frozen failed"
    return 1
  fi

  if uv run python -c "import ii_agent" >/dev/null 2>&1; then
    ok "Python dependencies are available after repair"
  else
    fail "Python environment is still not importable after uv sync"
    return 1
  fi
}

ensure_frontend_environment() {
  if [[ $BACKEND_ONLY -eq 1 ]]; then
    return 0
  fi

  ensure_command "node" "Install Node.js from https://nodejs.org/ or via nvm" || return 1
  ensure_command "npm" "Install npm with Node.js from https://nodejs.org/ or via nvm" || return 1

  if [[ -d "$FRONTEND_DIR/node_modules" ]]; then
    ok "Frontend dependencies are installed"
    return 0
  fi

  if [[ $AUTO_HEAL -ne 1 ]]; then
    fail "Frontend dependencies are missing; run 'npm --prefix frontend install' or rerun without --no-heal"
    return 1
  fi

  info "Frontend dependencies are missing; running npm install in frontend/"
  if npm --prefix "$FRONTEND_DIR" install; then
    repair "Installed frontend dependencies with npm"
    return 0
  fi

  fail "npm install failed in frontend/"
  return 1
}

make_temp_file() {
  mktemp -t ii-agent-start 2>/dev/null || mktemp "${TMPDIR:-/tmp}/ii-agent-start.XXXXXX"
}

persist_env_var() {
  local name="$1"
  local value="$2"
  local tmp_file

  tmp_file=$(make_temp_file)
  if awk -v name="$name" -v value="$value" '
    BEGIN { updated = 0 }
    $0 ~ "^[[:space:]]*(export[[:space:]]+)?" name "=" {
      print name "=" value
      updated = 1
      next
    }
    { print }
    END {
      if (!updated) {
        print name "=" value
      }
    }
  ' "$ENV_FILE" >"$tmp_file"; then
    mv "$tmp_file" "$ENV_FILE"
    return 0
  fi

  rm -f "$tmp_file"
  return 1
}

load_runtime_facts() {
  local facts_file
  local rc
  facts_file=$(make_temp_file)
  uv run python "$PREFLIGHT_HELPER" facts >"$facts_file"
  rc=$?

  if [[ $rc -ne 0 ]]; then
    rm -f "$facts_file"
    fail "Failed to resolve runtime settings from project configuration"
    return 1
  fi

  # shellcheck disable=SC1090
  . "$facts_file"
  rm -f "$facts_file"
  ok "Resolved runtime configuration"
}

docker_is_ready() {
  command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1
}

resolve_sandbox_runtime_binary() {
  if command -v podman >/dev/null 2>&1; then
    printf 'podman\n'
    return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    printf 'docker\n'
    return 0
  fi
  return 1
}

collect_local_sandbox_containers() {
  local runtime_binary="$1"

  {
    "$runtime_binary" ps -aq \
      --filter "label=ii_agent.managed=true" \
      --filter "label=ii_agent.role=sandbox" \
      --filter "label=ii_agent.project_name=$COMPOSE_PROJECT_NAME" 2>/dev/null || true

    if [[ -n "$RUNTIME_SANDBOX_DOCKER_IMAGE" ]]; then
      "$runtime_binary" ps -aq \
        --filter "ancestor=$RUNTIME_SANDBOX_DOCKER_IMAGE" \
        --filter "name=ii-agent-sandbox-" 2>/dev/null || true
    fi
  } | awk 'NF && !seen[$0]++'
}

cleanup_local_sandbox_containers() {
  local phase="$1"

  if [[ "$RUNTIME_SANDBOX_PROVIDER" != "docker" ]]; then
    return 0
  fi

  local runtime_binary
  runtime_binary=$(resolve_sandbox_runtime_binary) || return 0

  local container_output
  container_output=$(collect_local_sandbox_containers "$runtime_binary")
  if [[ -z "$container_output" ]]; then
    return 0
  fi

  local container_ids=()
  local container_id
  while IFS= read -r container_id; do
    if [[ -n "$container_id" ]]; then
      container_ids+=("$container_id")
    fi
  done <<< "$container_output"

  if [[ ${#container_ids[@]} -eq 0 ]]; then
    return 0
  fi

  info "Removing ${#container_ids[@]} local sandbox container(s) during $phase"
  if "$runtime_binary" rm -f "${container_ids[@]}" >/dev/null 2>&1; then
    ok "Removed ${#container_ids[@]} local sandbox container(s) for project $COMPOSE_PROJECT_NAME"
  else
    warn "Failed to remove local sandbox containers for project $COMPOSE_PROJECT_NAME"
  fi
}

start_local_infra() {
  if [[ ! -f "$COMPOSE_DEV_FILE" ]]; then
    fail "Cannot auto-start local infra: missing $COMPOSE_DEV_FILE"
    return 1
  fi

  if ! command -v docker >/dev/null 2>&1; then
    fail "Cannot auto-start local infra: docker is not installed"
    return 1
  fi

  if ! docker info >/dev/null 2>&1; then
    fail "Cannot auto-start local infra: Docker daemon is not running"
    return 1
  fi

  info "Starting local infrastructure with docker compose"
  if docker compose --project-name "$COMPOSE_PROJECT_NAME" -f "$COMPOSE_DEV_FILE" up -d postgres redis minio; then
    repair "Started local Postgres, Redis, and MinIO via docker compose"
  else
    fail "docker compose failed to start local infrastructure"
    return 1
  fi
}

daytona_url_component() {
  local url="$1"
  local component="$2"
  uv run python - "$url" "$component" <<'PY'
import sys
from urllib.parse import urlparse

parsed = urlparse(sys.argv[1])
component = sys.argv[2]

if component == "host":
    print(parsed.hostname or "")
elif component == "port":
    if parsed.port:
        print(parsed.port)
    elif parsed.scheme == "https":
        print("443")
    else:
        print("80")
else:
    raise SystemExit(f"unsupported URL component: {component}")
PY
}

daytona_url_with_port() {
  local url="$1"
  local port="$2"
  uv run python - "$url" "$port" <<'PY'
import sys
from urllib.parse import urlparse, urlunparse

parsed = urlparse(sys.argv[1])
port = sys.argv[2]
host = parsed.hostname or "localhost"
scheme = parsed.scheme or "http"
userinfo = ""
if parsed.username:
    userinfo = parsed.username
    if parsed.password:
        userinfo += f":{parsed.password}"
    userinfo += "@"
if ":" in host and not host.startswith("["):
    host = f"[{host}]"
netloc = f"{userinfo}{host}:{port}"
path = parsed.path or "/api"
print(urlunparse((scheme, netloc, path, parsed.params, parsed.query, parsed.fragment)))
PY
}

is_local_daytona_url() {
  local host
  host=$(daytona_url_component "$RUNTIME_SANDBOX_DAYTONA_API_URL" host)
  [[ "$host" == "localhost" || "$host" == "127.0.0.1" || "$host" == "::1" ]]
}

daytona_port_is_reserved() {
  local port="$1"
  local reserved
  for reserved in "${DAYTONA_RESERVED_PORTS[@]}"; do
    if [[ "$reserved" == "$port" ]]; then
      return 0
    fi
  done
  return 1
}

daytona_port_in_use() {
  local port="$1"
  ! uv run python "$PREFLIGHT_HELPER" check-port --host "0.0.0.0" --port "$port" >/dev/null 2>&1
}

choose_daytona_port_var() {
  local var_name="$1"
  local requested="$2"
  local max_offset="${3:-80}"
  local port="$requested"
  local max_port=$((requested + max_offset))

  while ((port <= max_port)); do
    if ! daytona_port_is_reserved "$port" && ! daytona_port_in_use "$port"; then
      printf -v "$var_name" '%s' "$port"
      DAYTONA_RESERVED_PORTS+=("$port")
      return 0
    fi
    port=$((port + 1))
  done

  fail "No free Daytona port found in range ${requested}-${max_port}"
  return 1
}

select_daytona_ports() {
  DAYTONA_RESERVED_PORTS=()

  local configured_api_port
  configured_api_port=$(daytona_url_component "$RUNTIME_SANDBOX_DAYTONA_API_URL" port)
  if [[ ! "$configured_api_port" =~ ^[0-9]+$ ]]; then
    fail "Could not resolve Daytona API port from $RUNTIME_SANDBOX_DAYTONA_API_URL"
    return 1
  fi

  local api_start="${II_AGENT_DAYTONA_API_PORT:-$configured_api_port}"
  if [[ "$api_start" == "3000" ]] && daytona_port_in_use "$api_start"; then
    api_start=3980
  fi

  choose_daytona_port_var DAYTONA_API_HOST_PORT "$api_start" || return 1
  choose_daytona_port_var DAYTONA_PROXY_HOST_PORT "${II_AGENT_DAYTONA_PROXY_PORT:-$((DAYTONA_API_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_RUNNER_HOST_PORT "${II_AGENT_DAYTONA_RUNNER_PORT:-$((DAYTONA_PROXY_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_SSH_HOST_PORT "${II_AGENT_DAYTONA_SSH_PORT:-$((DAYTONA_RUNNER_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_DEX_HOST_PORT "${II_AGENT_DAYTONA_DEX_PORT:-$((DAYTONA_SSH_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_PGADMIN_HOST_PORT "${II_AGENT_DAYTONA_PGADMIN_PORT:-$((DAYTONA_DEX_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_REGISTRY_UI_HOST_PORT "${II_AGENT_DAYTONA_REGISTRY_UI_PORT:-$((DAYTONA_PGADMIN_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_REGISTRY_HOST_PORT "${II_AGENT_DAYTONA_REGISTRY_PORT:-$((DAYTONA_REGISTRY_UI_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_MAILDEV_HOST_PORT "${II_AGENT_DAYTONA_MAILDEV_PORT:-$((DAYTONA_REGISTRY_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_MINIO_CONSOLE_HOST_PORT "${II_AGENT_DAYTONA_MINIO_CONSOLE_PORT:-$((DAYTONA_MAILDEV_HOST_PORT + 1))}" || return 1
  choose_daytona_port_var DAYTONA_JAEGER_HOST_PORT "${II_AGENT_DAYTONA_JAEGER_PORT:-$((DAYTONA_MINIO_CONSOLE_HOST_PORT + 1))}" || return 1

  if [[ "$DAYTONA_API_HOST_PORT" != "$configured_api_port" ]]; then
    export SANDBOX_DAYTONA_API_URL
    SANDBOX_DAYTONA_API_URL=$(daytona_url_with_port "$RUNTIME_SANDBOX_DAYTONA_API_URL" "$DAYTONA_API_HOST_PORT")
    RUNTIME_SANDBOX_DAYTONA_API_URL="$SANDBOX_DAYTONA_API_URL"
    repair "Selected Daytona API port $DAYTONA_API_HOST_PORT and exported SANDBOX_DAYTONA_API_URL=$SANDBOX_DAYTONA_API_URL"
  fi
}

daytona_compose_host_port() {
  local container_port="$1"
  local occurrence="${2:-1}"
  if [[ ! -f "$DAYTONA_COMPOSE_FILE" ]]; then
    return 1
  fi
  awk -v target=":$container_port" -v occurrence="$occurrence" '
    BEGIN { seen = 0 }
    $1 == "-" && $2 ~ "^[0-9]+:[0-9]+$" && $2 ~ target "$" {
      seen += 1
      if (seen != occurrence) {
        next
      }
      split($2, parts, ":")
      print parts[1]
      exit
    }
  ' "$DAYTONA_COMPOSE_FILE"
}

load_daytona_ports_from_compose_file() {
  local spec
  local value
  for spec in \
    DAYTONA_API_HOST_PORT:3000:1 \
    DAYTONA_PROXY_HOST_PORT:4000:1 \
    DAYTONA_RUNNER_HOST_PORT:3003:1 \
    DAYTONA_SSH_HOST_PORT:2222:1 \
    DAYTONA_DEX_HOST_PORT:5556:1 \
    DAYTONA_PGADMIN_HOST_PORT:80:1 \
    DAYTONA_REGISTRY_UI_HOST_PORT:80:2 \
    DAYTONA_REGISTRY_HOST_PORT:6000:1 \
    DAYTONA_MAILDEV_HOST_PORT:1080:1 \
    DAYTONA_MINIO_CONSOLE_HOST_PORT:9001:1 \
    DAYTONA_JAEGER_HOST_PORT:16686:1; do
    value=$(daytona_compose_host_port "$(printf '%s' "$spec" | cut -d: -f2)" "$(printf '%s' "$spec" | cut -d: -f3)")
    if [[ ! "$value" =~ ^[0-9]+$ ]]; then
      return 1
    fi
    printf -v "${spec%%:*}" '%s' "$value"
  done
  return 0
}

ensure_daytona_repo() {
  if [[ -f "$DAYTONA_REPO_DIR/docker/docker-compose.yaml" ]]; then
    ok "Using Daytona OSS checkout at $DAYTONA_REPO_DIR"
    return 0
  fi

  if [[ -e "$DAYTONA_REPO_DIR" ]]; then
    fail "Cannot auto-start Daytona: $DAYTONA_REPO_DIR exists but does not contain docker/docker-compose.yaml"
    return 1
  fi

  if ! command -v git >/dev/null 2>&1; then
    fail "Cannot auto-start Daytona: git is not installed"
    return 1
  fi

  mkdir -p "$DAYTONA_CACHE_DIR"
  info "Cloning Daytona OSS runtime into $DAYTONA_REPO_DIR"
  if git clone --depth 1 --branch "$DAYTONA_REPO_REF" "$DAYTONA_REPO_URL" "$DAYTONA_REPO_DIR"; then
    repair "Cloned Daytona OSS runtime from $DAYTONA_REPO_URL ($DAYTONA_REPO_REF)"
    return 0
  fi

  fail "Failed to clone Daytona OSS runtime from $DAYTONA_REPO_URL"
  return 1
}

generate_daytona_compose_file() {
  local source_file="$DAYTONA_REPO_DIR/docker/docker-compose.yaml"
  mkdir -p "$(dirname "$DAYTONA_COMPOSE_FILE")"

  DAYTONA_API_HOST_PORT="$DAYTONA_API_HOST_PORT" \
  DAYTONA_PROXY_HOST_PORT="$DAYTONA_PROXY_HOST_PORT" \
  DAYTONA_RUNNER_HOST_PORT="$DAYTONA_RUNNER_HOST_PORT" \
  DAYTONA_SSH_HOST_PORT="$DAYTONA_SSH_HOST_PORT" \
  DAYTONA_DEX_HOST_PORT="$DAYTONA_DEX_HOST_PORT" \
  DAYTONA_PGADMIN_HOST_PORT="$DAYTONA_PGADMIN_HOST_PORT" \
  DAYTONA_REGISTRY_UI_HOST_PORT="$DAYTONA_REGISTRY_UI_HOST_PORT" \
  DAYTONA_REGISTRY_HOST_PORT="$DAYTONA_REGISTRY_HOST_PORT" \
  DAYTONA_MAILDEV_HOST_PORT="$DAYTONA_MAILDEV_HOST_PORT" \
  DAYTONA_MINIO_CONSOLE_HOST_PORT="$DAYTONA_MINIO_CONSOLE_HOST_PORT" \
  DAYTONA_JAEGER_HOST_PORT="$DAYTONA_JAEGER_HOST_PORT" \
  DAYTONA_OUTER_NETWORK_SUBNET="$DAYTONA_OUTER_NETWORK_SUBNET" \
  uv run python - "$source_file" "$DAYTONA_COMPOSE_FILE" <<'PY'
import os
import sys
from pathlib import Path

source = Path(sys.argv[1])
target = Path(sys.argv[2])
text = source.read_text()

api = os.environ["DAYTONA_API_HOST_PORT"]
proxy = os.environ["DAYTONA_PROXY_HOST_PORT"]
runner = os.environ["DAYTONA_RUNNER_HOST_PORT"]
ssh = os.environ["DAYTONA_SSH_HOST_PORT"]
dex = os.environ["DAYTONA_DEX_HOST_PORT"]
pgadmin = os.environ["DAYTONA_PGADMIN_HOST_PORT"]
registry_ui = os.environ["DAYTONA_REGISTRY_UI_HOST_PORT"]
registry = os.environ["DAYTONA_REGISTRY_HOST_PORT"]
maildev = os.environ["DAYTONA_MAILDEV_HOST_PORT"]
minio_console = os.environ["DAYTONA_MINIO_CONSOLE_HOST_PORT"]
jaeger = os.environ["DAYTONA_JAEGER_HOST_PORT"]
outer_network_subnet = os.environ["DAYTONA_OUTER_NETWORK_SUBNET"]

replacements = {
    "3000:3000": f"{api}:3000",
    "4000:4000": f"{proxy}:4000",
    "3003:3003": f"{runner}:3003",
    "2222:2222": f"{ssh}:2222",
    "5556:5556": f"{dex}:5556",
    "5050:80": f"{pgadmin}:80",
    "5100:80": f"{registry_ui}:80",
    "6000:6000": f"{registry}:6000",
    "1080:1080": f"{maildev}:1080",
    "9001:9001": f"{minio_console}:9001",
    "16686:16686": f"{jaeger}:16686",
    "DASHBOARD_URL=http://localhost:3000/dashboard": f"DASHBOARD_URL=http://localhost:{api}/dashboard",
    "DASHBOARD_BASE_API_URL=http://localhost:3000": f"DASHBOARD_BASE_API_URL=http://localhost:{api}",
    "PUBLIC_OIDC_DOMAIN=http://localhost:5556/dex": f"PUBLIC_OIDC_DOMAIN=http://localhost:{dex}/dex",
    "OIDC_PUBLIC_DOMAIN=http://localhost:5556/dex": f"OIDC_PUBLIC_DOMAIN=http://localhost:{dex}/dex",
    "PROXY_DOMAIN=proxy.localhost:4000": f"PROXY_DOMAIN=proxy.localhost:{proxy}",
    "PROXY_TEMPLATE_URL=http://{{PORT}}-{{sandboxId}}.proxy.localhost:4000": (
        f"PROXY_TEMPLATE_URL=http://{{{{PORT}}}}-{{{{sandboxId}}}}.proxy.localhost:{proxy}"
    ),
    "SSH_GATEWAY_COMMAND=ssh -p 2222 {{TOKEN}}@localhost": f"SSH_GATEWAY_COMMAND=ssh -p {ssh} {{{{TOKEN}}}}@localhost",
    "SSH_GATEWAY_URL=localhost:2222": f"SSH_GATEWAY_URL=localhost:{ssh}",
    "HEALTH_CHECK_API_KEY=supersecretkey": "\n".join(
        [
            "HEALTH_CHECK_API_KEY=supersecretkey",
            "      - ADMIN_API_KEY=supersecret",
            "      - ADMIN_TOTAL_CPU_QUOTA=1000",
            "      - ADMIN_TOTAL_MEMORY_QUOTA=1000",
            "      - ADMIN_TOTAL_DISK_QUOTA=10000",
            "      - ADMIN_MAX_CPU_PER_SANDBOX=4",
            "      - ADMIN_MAX_MEMORY_PER_SANDBOX=8",
            "      - ADMIN_MAX_DISK_PER_SANDBOX=50",
            "      - ADMIN_SNAPSHOT_QUOTA=1000",
            "      - ADMIN_MAX_SNAPSHOT_SIZE=1000",
            "      - ADMIN_VOLUME_QUOTA=1000",
        ]
    ),
}

missing = [old for old in replacements if old not in text]
if missing:
    raise SystemExit(
        "Daytona compose template no longer matches expected upstream shape; missing: "
        + ", ".join(missing)
    )

for old, new in replacements.items():
    text = text.replace(old, new)

network_block = "networks:\n  daytona-network:\n    driver: bridge\n"
if network_block not in text:
    raise SystemExit("Daytona compose template no longer has the expected daytona-network block")
text = text.replace(
    network_block,
    "\n".join(
        [
            "networks:",
            "  daytona-network:",
            "    driver: bridge",
            "    ipam:",
            "      config:",
            f"        - subnet: {outer_network_subnet}",
            "",
        ]
    ),
)

target.write_text(
    "# Generated by ii-agent scripts/start.sh. Do not edit by hand.\n" + text
)
PY
}

start_daytona_stack() {
  if ! command -v docker >/dev/null 2>&1; then
    fail "Cannot auto-start Daytona: docker is not installed"
    return 1
  fi

  if ! docker info >/dev/null 2>&1; then
    fail "Cannot auto-start Daytona: Docker daemon is not running"
    return 1
  fi

  ensure_daytona_repo || return 1
  generate_daytona_compose_file || {
    fail "Failed to generate Daytona compose file"
    return 1
  }

  if [[ ! "$DAYTONA_COMPOSE_ATTEMPTS" =~ ^[0-9]+$ || "$DAYTONA_COMPOSE_ATTEMPTS" -lt 1 ]]; then
    DAYTONA_COMPOSE_ATTEMPTS=3
  fi

  local attempt=1
  while ((attempt <= DAYTONA_COMPOSE_ATTEMPTS)); do
    info "Starting Daytona OSS stack with docker compose on API port $DAYTONA_API_HOST_PORT (attempt $attempt/$DAYTONA_COMPOSE_ATTEMPTS, parallel limit $DAYTONA_COMPOSE_PARALLEL_LIMIT)"
    if COMPOSE_PARALLEL_LIMIT="$DAYTONA_COMPOSE_PARALLEL_LIMIT" docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" up -d; then
      repair "Started Daytona OSS stack via docker compose ($DAYTONA_COMPOSE_PROJECT_NAME)"
      return 0
    fi

    if ((attempt < DAYTONA_COMPOSE_ATTEMPTS)); then
      warn "docker compose failed to start Daytona OSS stack; retrying in case this was a transient image pull failure"
      sleep 5
    fi
    attempt=$((attempt + 1))
  done

  fail "docker compose failed to start Daytona OSS stack"
  return 1
}

ensure_daytona_outer_network_if_needed() {
  if ! is_local_daytona_url || [[ ! -f "$DAYTONA_COMPOSE_FILE" ]]; then
    return 0
  fi
  if ! docker_is_ready; then
    return 0
  fi

  local network_name="${DAYTONA_COMPOSE_PROJECT_NAME}_daytona-network"
  local subnet
  subnet=$(docker network inspect -f '{{range .IPAM.Config}}{{.Subnet}}{{end}}' "$network_name" 2>/dev/null || true)
  if [[ -z "$subnet" || "$subnet" == "$DAYTONA_OUTER_NETWORK_SUBNET" ]]; then
    return 0
  fi

  warn "Daytona compose network $network_name uses $subnet; recreating it on $DAYTONA_OUTER_NETWORK_SUBNET to avoid the runner's hardcoded nested 172.20.0.0/16 bridge"
  if ! load_daytona_ports_from_compose_file; then
    fail "Cannot recreate Daytona network because existing generated compose ports could not be read"
    return 1
  fi
  generate_daytona_compose_file || return 1
  if ! docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" down --remove-orphans; then
    fail "Failed to stop Daytona OSS stack before network recreation"
    return 1
  fi
  if ! COMPOSE_PARALLEL_LIMIT="$DAYTONA_COMPOSE_PARALLEL_LIMIT" docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" up -d; then
    fail "Failed to restart Daytona OSS stack after network recreation"
    return 1
  fi
  wait_for_probe "Daytona API health endpoint" probe_daytona_health 90 2 || return 1
  repair "Recreated Daytona compose network on $DAYTONA_OUTER_NETWORK_SUBNET"
}

create_daytona_admin_api_key() {
  local key_name="${II_AGENT_DAYTONA_ADMIN_API_KEY_NAME:-ii-agent-local-$(date +%Y%m%d%H%M%S)}"
  local output
  local api_key

  if [[ ! -f "$DAYTONA_COMPOSE_FILE" ]]; then
    fail "Cannot create Daytona API key: missing generated compose file $DAYTONA_COMPOSE_FILE"
    return 1
  fi

  info "Creating Daytona admin API key for local stack"
  if ! output=$(docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" exec -T api node dist/apps/api/main.js --create-admin-api-key "$key_name" 2>&1); then
    fail "Failed to create Daytona admin API key. Details: $(printf '%s' "$output" | tail -n 1)"
    return 1
  fi

  api_key=$(printf '%s\n' "$output" | grep -Eo 'dtn_[[:alnum:]]+' | tail -n 1)
  if [[ -z "$api_key" ]]; then
    fail "Failed to parse Daytona admin API key from create-admin-api-key output"
    return 1
  fi

  export SANDBOX_DAYTONA_API_KEY="$api_key"
  RUNTIME_SANDBOX_DAYTONA_API_KEY_PRESENT=1
  if persist_env_var "SANDBOX_DAYTONA_API_KEY" "$api_key"; then
    repair "Created Daytona admin API key for local stack and persisted SANDBOX_DAYTONA_API_KEY in $ENV_FILE"
  else
    fail "Created Daytona admin API key but failed to persist SANDBOX_DAYTONA_API_KEY in $ENV_FILE"
    return 1
  fi
}

repair_daytona_admin_quota() {
  local org_id
  local needs_repair

  if [[ ! -f "$DAYTONA_COMPOSE_FILE" ]]; then
    fail "Cannot repair Daytona admin quota: missing generated compose file $DAYTONA_COMPOSE_FILE"
    return 1
  fi

  org_id=$(docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" exec -T db \
    psql -U user -d daytona -At -c "select id from organization where \"createdBy\" = 'daytona-admin' and personal is true order by \"createdAt\" limit 1" 2>/dev/null | tr -d '[:space:]')
  if [[ -z "$org_id" ]]; then
    fail "Cannot repair Daytona admin quota: admin personal organization was not found"
    return 1
  fi

  needs_repair=$(docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" exec -T db \
    psql -U user -d daytona -At -c "select case when coalesce(max_cpu_per_sandbox, 0) < 1 or coalesce(max_memory_per_sandbox, 0) < 1 or coalesce(max_disk_per_sandbox, 0) < 3 or coalesce(volume_quota, 0) < 1 then '1' else '0' end from organization where id = '$org_id'::uuid" 2>/dev/null | tr -d '[:space:]')

  if [[ "$needs_repair" != "1" ]]; then
    ok "Daytona admin organization quota is usable"
    return 0
  fi

  if docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" exec -T db \
    psql -U user -d daytona -v ON_ERROR_STOP=1 -c "update organization set max_cpu_per_sandbox = 4, max_memory_per_sandbox = 8, max_disk_per_sandbox = 50, snapshot_quota = 1000, max_snapshot_size = 1000, volume_quota = 1000, \"updatedAt\" = now() where id = '$org_id'::uuid; insert into region_quota (\"organizationId\", \"regionId\", total_cpu_quota, total_memory_quota, total_disk_quota, max_cpu_per_sandbox, max_memory_per_sandbox, max_disk_per_sandbox, max_disk_per_non_ephemeral_sandbox, \"createdAt\", \"updatedAt\") values ('$org_id'::uuid, 'us', 1000, 1000, 10000, 4, 8, 50, 50, now(), now()) on conflict (\"organizationId\", \"regionId\") do update set total_cpu_quota = excluded.total_cpu_quota, total_memory_quota = excluded.total_memory_quota, total_disk_quota = excluded.total_disk_quota, max_cpu_per_sandbox = excluded.max_cpu_per_sandbox, max_memory_per_sandbox = excluded.max_memory_per_sandbox, max_disk_per_sandbox = excluded.max_disk_per_sandbox, max_disk_per_non_ephemeral_sandbox = excluded.max_disk_per_non_ephemeral_sandbox, \"updatedAt\" = now();" >/dev/null; then
    repair "Repaired Daytona admin organization quota for local sandbox creation"
    return 0
  fi

  fail "Failed to repair Daytona admin organization quota"
  return 1
}

daytona_registry_host_image() {
  if [[ -z "${DAYTONA_REGISTRY_HOST_PORT:-}" ]]; then
    load_daytona_ports_from_compose_file || true
  fi
  if [[ -z "${DAYTONA_REGISTRY_HOST_PORT:-}" ]]; then
    return 1
  fi
  printf 'localhost:%s/%s:%s\n' "$DAYTONA_REGISTRY_HOST_PORT" "$DAYTONA_LOCAL_SANDBOX_IMAGE_REPOSITORY" "$DAYTONA_LOCAL_SANDBOX_IMAGE_TAG"
}

daytona_registry_internal_image() {
  printf 'registry:6000/%s:%s\n' "$DAYTONA_LOCAL_SANDBOX_IMAGE_REPOSITORY" "$DAYTONA_LOCAL_SANDBOX_IMAGE_TAG"
}

daytona_registry_has_amd64_image() {
  local image_ref="$1"
  docker buildx imagetools inspect "$image_ref" 2>/dev/null | grep -Eq 'Platform:[[:space:]]+linux/amd64'
}

ensure_daytona_sandbox_image_if_needed() {
  if [[ "$RUNTIME_SANDBOX_DAYTONA_DEFAULT_IMAGE" != "ii-agent-codex-sandbox:local" ]]; then
    return 0
  fi

  local host_image
  local internal_image
  host_image=$(daytona_registry_host_image) || {
    fail "Cannot prepare Daytona sandbox image: local Daytona registry port is unknown"
    return 1
  }
  internal_image=$(daytona_registry_internal_image)

  if daytona_registry_has_amd64_image "$host_image"; then
    ok "Daytona-local amd64 sandbox image is available in $host_image"
  else
    if [[ "$DAYTONA_AUTO_BUILD_SANDBOX_IMAGE" != "1" && "$DAYTONA_AUTO_BUILD_SANDBOX_IMAGE" != "true" ]]; then
      fail "Daytona needs an amd64 sandbox image in $host_image; set II_AGENT_DAYTONA_AUTO_BUILD_SANDBOX_IMAGE=1 or publish one manually"
      return 1
    fi

    if [[ ! -f "$DAYTONA_SANDBOX_DOCKERFILE" ]]; then
      fail "Daytona sandbox Dockerfile is missing: $DAYTONA_SANDBOX_DOCKERFILE"
      return 1
    fi

    local codex_cli_version
    codex_cli_version="${RUNTIME_SANDBOX_CODEX_CLI_PACKAGE##*@}"
    if [[ -z "$codex_cli_version" || "$codex_cli_version" == "codex" ]]; then
      codex_cli_version="0.124.0"
    fi

    info "Building linux/amd64 Daytona sandbox image from $DAYTONA_SANDBOX_DOCKERFILE and pushing to $host_image"
    if docker buildx build --network host --platform linux/amd64 \
      --build-arg "OPENAI_CODEX_CLI_VERSION=$codex_cli_version" \
      -f "$DAYTONA_SANDBOX_DOCKERFILE" -t "$host_image" --push "$REPO_ROOT"; then
      repair "Built and pushed Daytona linux/amd64 sandbox image to $host_image"
    else
      fail "Failed to build and push Daytona linux/amd64 sandbox image to $host_image"
      return 1
    fi
  fi

  export SANDBOX_DAYTONA_DEFAULT_IMAGE="$internal_image"
  RUNTIME_SANDBOX_DAYTONA_DEFAULT_IMAGE="$internal_image"
  if persist_env_var "SANDBOX_DAYTONA_DEFAULT_IMAGE" "$internal_image"; then
    repair "Configured Daytona sandbox image for runner-visible local registry: $internal_image"
  else
    fail "Failed to persist SANDBOX_DAYTONA_DEFAULT_IMAGE in $ENV_FILE"
    return 1
  fi
}

repair_daytona_local_build_cache() {
  if [[ "$RUNTIME_SANDBOX_DAYTONA_DEFAULT_IMAGE" != registry:6000/* ]]; then
    return 0
  fi
  if [[ ! -f "$DAYTONA_COMPOSE_FILE" ]] || ! docker_is_ready; then
    return 0
  fi

  local output
  if output=$(docker compose --project-name "$DAYTONA_COMPOSE_PROJECT_NAME" -f "$DAYTONA_COMPOSE_FILE" exec -T db \
    psql -U user -d daytona -v ON_ERROR_STOP=1 -v image="$RUNTIME_SANDBOX_DAYTONA_DEFAULT_IMAGE" <<'SQL' 2>&1
create temporary table ii_agent_daytona_repair_target (
  "snapshotRef" varchar primary key
);

insert into ii_agent_daytona_repair_target ("snapshotRef")
select b."snapshotRef"
from build_info b
where b."dockerfileContent" = concat('FROM ', :'image', E'\n')
  and (
    exists (
      select 1 from sandbox s
      where s."buildInfoSnapshotRef" = b."snapshotRef"
        and s.state::text in ('error','destroyed','build_failed','unknown')
    )
    or exists (
      select 1 from snapshot sn
      where sn."buildInfoSnapshotRef" = b."snapshotRef"
        and sn.state::text in ('error','build_failed','unknown')
    )
    or exists (
      select 1 from snapshot_runner sr
      where sr."snapshotRef" = b."snapshotRef"
        and sr.state::text in ('error','removing')
    )
  )
on conflict do nothing;

delete from sandbox
where "buildInfoSnapshotRef" in (select "snapshotRef" from ii_agent_daytona_repair_target)
  and state::text in ('error','destroyed','build_failed','unknown');

delete from snapshot
where "buildInfoSnapshotRef" in (select "snapshotRef" from ii_agent_daytona_repair_target)
  and state::text in ('error','build_failed','unknown');

delete from snapshot_runner
where "snapshotRef" in (select "snapshotRef" from ii_agent_daytona_repair_target);

delete from build_info b
using ii_agent_daytona_repair_target target
where b."snapshotRef" = target."snapshotRef"
  and not exists (
    select 1 from sandbox s where s."buildInfoSnapshotRef" = b."snapshotRef"
  )
  and not exists (
    select 1 from snapshot sn where sn."buildInfoSnapshotRef" = b."snapshotRef"
  );
SQL
  ); then
    if printf '%s\n' "$output" | grep -Eq 'DELETE [1-9]'; then
      repair "Cleared stale Daytona build cache for $RUNTIME_SANDBOX_DAYTONA_DEFAULT_IMAGE"
    fi
    return 0
  fi

  fail "Failed to repair Daytona build cache. Details: $(printf '%s' "$output" | tail -n 1)"
  return 1
}

ensure_daytona_api_key_if_needed() {
  if probe_daytona_api >/dev/null 2>&1; then
    ok "Daytona API is reachable at $RUNTIME_SANDBOX_DAYTONA_API_URL"
    return 0
  fi

  if [[ $AUTO_HEAL -ne 1 ]]; then
    fail "Daytona API is reachable but not authenticated; rerun without --no-heal to create a local Daytona API key"
    return 1
  fi

  if ! is_local_daytona_url; then
    fail "Daytona API at $RUNTIME_SANDBOX_DAYTONA_API_URL requires credentials; set SANDBOX_DAYTONA_API_KEY"
    return 1
  fi

  if ! probe_daytona_health >/dev/null 2>&1; then
    fail "Cannot create Daytona API key because Daytona health endpoint is not reachable"
    return 1
  fi

  create_daytona_admin_api_key || return 1

  if probe_daytona_api >/dev/null 2>&1; then
    ok "Daytona API is reachable at $RUNTIME_SANDBOX_DAYTONA_API_URL"
    return 0
  fi

  fail "Created a Daytona API key, but the authenticated Daytona API probe still failed"
  return 1
}

ensure_daytona_service_if_needed() {
  if [[ "$RUNTIME_SANDBOX_PROVIDER" != "daytona" ]]; then
    return 0
  fi

  if [[ $RUNTIME_SANDBOX_READY -ne 1 ]]; then
    fail "SANDBOX_PROVIDER=daytona but SANDBOX_DAYTONA_API_URL is not set"
    return 1
  fi

  ensure_daytona_outer_network_if_needed || return 1

  if probe_daytona_api >/dev/null 2>&1; then
    ok "Daytona API is reachable at $RUNTIME_SANDBOX_DAYTONA_API_URL"
    if is_local_daytona_url; then
      repair_daytona_admin_quota || return 1
      ensure_daytona_sandbox_image_if_needed || return 1
      repair_daytona_local_build_cache || return 1
    fi
    return 0
  fi

  if probe_daytona_health >/dev/null 2>&1; then
    ensure_daytona_api_key_if_needed || return 1
    repair_daytona_admin_quota || return 1
    ensure_daytona_sandbox_image_if_needed
    repair_daytona_local_build_cache || return 1
    return 0
  fi

  if ! is_local_daytona_url; then
    fail "Daytona API is not reachable at $RUNTIME_SANDBOX_DAYTONA_API_URL and start.sh can only auto-start local Daytona deployments"
    return 1
  fi

  if [[ $AUTO_HEAL -ne 1 ]]; then
    fail "Daytona API is not reachable at $RUNTIME_SANDBOX_DAYTONA_API_URL; rerun without --no-heal to auto-start local Daytona"
    return 1
  fi

  select_daytona_ports || return 1
  start_daytona_stack || return 1
  wait_for_probe "Daytona API health endpoint" probe_daytona_health 90 2 || return 1
  ensure_daytona_api_key_if_needed || return 1
  repair_daytona_admin_quota || return 1
  ensure_daytona_sandbox_image_if_needed || return 1
  repair_daytona_local_build_cache
}

probe_database() {
  uv run python "$PREFLIGHT_HELPER" probe-database
}

probe_redis() {
  uv run python "$PREFLIGHT_HELPER" probe-redis
}

probe_storage() {
  uv run python "$PREFLIGHT_HELPER" probe-storage
}

validate_libmagic() {
  local output

  if output=$(uv run python "$PREFLIGHT_HELPER" probe-libmagic 2>&1); then
    ok "libmagic runtime is available"
    return 0
  fi

  fail "libmagic runtime is unavailable. Install libmagic on the host (for macOS: 'brew install libmagic'). Details: $(printf '%s' "$output" | tail -n 1)"
  return 1
}

probe_app_import() {
  uv run python "$PREFLIGHT_HELPER" probe-app
}

probe_codex_app_server_image() {
  uv run python "$PREFLIGHT_HELPER" probe-codex-app-server-image
}

probe_daytona_api() {
  uv run python "$PREFLIGHT_HELPER" probe-daytona-api
}

probe_daytona_health() {
  uv run python "$PREFLIGHT_HELPER" probe-daytona-health
}

wait_for_probe() {
  local label="$1"
  local probe_function="$2"
  local attempts="${3:-30}"
  local delay_seconds="${4:-2}"
  local try=1

  while ((try <= attempts)); do
    if "$probe_function" >/dev/null 2>&1; then
      ok "$label is reachable"
      return 0
    fi
    sleep "$delay_seconds"
    ((try += 1))
  done

  fail "$label did not become reachable after $((attempts * delay_seconds)) seconds"
  return 1
}

ensure_local_services_if_needed() {
  local need_infra=0

  if [[ $RUNTIME_DATABASE_IS_LOCAL -eq 1 ]] && ! probe_database >/dev/null 2>&1; then
    need_infra=1
    warn "Local PostgreSQL is configured but not reachable"
  fi

  if [[ $RUNTIME_REDIS_ENABLED -eq 1 && $RUNTIME_REDIS_IS_LOCAL -eq 1 ]] && ! probe_redis >/dev/null 2>&1; then
    need_infra=1
    warn "Local Redis is enabled but not reachable"
  fi

  if [[ "$RUNTIME_STORAGE_PROVIDER" == "minio" && $RUNTIME_STORAGE_MINIO_IS_LOCAL -eq 1 ]] && ! probe_storage >/dev/null 2>&1; then
    need_infra=1
    warn "Local MinIO storage is configured but not reachable"
  fi

  if [[ $need_infra -ne 1 ]]; then
    return 0
  fi

  if [[ $AUTO_HEAL -ne 1 ]]; then
    fail "Local infrastructure is unavailable; rerun without --no-heal to auto-start docker services"
    return 1
  fi

  start_local_infra || return 1

  if [[ $RUNTIME_DATABASE_IS_LOCAL -eq 1 ]]; then
    wait_for_probe "PostgreSQL" probe_database || return 1
  fi
  if [[ $RUNTIME_REDIS_ENABLED -eq 1 && $RUNTIME_REDIS_IS_LOCAL -eq 1 ]]; then
    wait_for_probe "Redis" probe_redis || return 1
  fi
  if [[ "$RUNTIME_STORAGE_PROVIDER" == "minio" && $RUNTIME_STORAGE_MINIO_IS_LOCAL -eq 1 ]]; then
    wait_for_probe "MinIO" probe_storage || return 1
  fi
}

validate_llm_config() {
  if [[ $RUNTIME_MODEL_CONFIGS_PRESENT -eq 1 ]]; then
    ok "At least one LLM model configuration is present"
    return 0
  fi

  warn "No LLM model configuration found; startup will continue, but system LLM settings seeding is skipped until MODEL_CONFIGS or MODEL_CONFIGS_FILE is set (see model_configs.example.yaml)"
  return 0
}

validate_database() {
  if probe_database >/dev/null 2>&1; then
    ok "Database connectivity check passed"
  else
    fail "Database connectivity check failed for $RUNTIME_DATABASE_URL"
    return 1
  fi

  if uv run alembic upgrade head >/dev/null; then
    ok "Database migrations are up to date"
  else
    fail "Database migrations failed"
    return 1
  fi
}

validate_redis() {
  if [[ $RUNTIME_REDIS_ENABLED -ne 1 ]]; then
    ok "Redis session storage is disabled"
    return 0
  fi

  if probe_redis >/dev/null 2>&1; then
    ok "Redis connectivity check passed"
  else
    fail "Redis connectivity check failed for $RUNTIME_REDIS_URL"
    return 1
  fi
}

validate_storage() {
  if probe_storage >/dev/null 2>&1; then
    ok "Storage provider validation passed ($RUNTIME_STORAGE_PROVIDER)"
  else
    fail "Storage provider validation failed ($RUNTIME_STORAGE_PROVIDER)"
    return 1
  fi
}

validate_app_import() {
  if has_failure_matching "libmagic runtime is unavailable"; then
    warn "Skipping application import validation because libmagic is already known to be missing"
    return 0
  fi

  if probe_app_import >/dev/null 2>&1; then
    ok "Application import and app factory validation passed"
  else
    fail "Application failed to initialize from current configuration"
    return 1
  fi
}

validate_server_port() {
  local rc
  uv run python "$PREFLIGHT_HELPER" check-port --host "$SERVER_HOST" --port "$SERVER_PORT"
  rc=$?
  if [[ $rc -eq 0 ]]; then
    ok "Server port $SERVER_PORT is available on $SERVER_HOST"
  else
    fail "Server port $SERVER_PORT is already in use on $SERVER_HOST"
    return 1
  fi
}

validate_frontend_port() {
  if [[ $BACKEND_ONLY -eq 1 ]]; then
    return 0
  fi

  if [[ ! "$FRONTEND_PORT" =~ ^[0-9]+$ ]]; then
    fail "Frontend port must be numeric, got: $FRONTEND_PORT"
    return 1
  fi

  local rc
  uv run python "$PREFLIGHT_HELPER" check-port --host "$FRONTEND_HOST" --port "$FRONTEND_PORT"
  rc=$?
  if [[ $rc -eq 0 ]]; then
    ok "Frontend port $FRONTEND_PORT is available on $FRONTEND_HOST"
  else
    fail "Frontend port $FRONTEND_PORT is already in use on $FRONTEND_HOST"
    return 1
  fi
}

validate_optional_integrations() {
  if has_failure_matching "Daytona API is not reachable"; then
    return 0
  fi
  if has_failure_matching "docker compose failed to start Daytona"; then
    return 0
  fi

  if [[ "$RUNTIME_SANDBOX_PROVIDER" == "e2b" && $RUNTIME_SANDBOX_READY -ne 1 ]]; then
    warn "SANDBOX_PROVIDER=e2b but SANDBOX_E2B_API_KEY is not set; sandbox features will fail at runtime"
  elif [[ "$RUNTIME_SANDBOX_PROVIDER" == "daytona" && $RUNTIME_SANDBOX_READY -ne 1 ]]; then
    fail "SANDBOX_PROVIDER=daytona but SANDBOX_DAYTONA_API_URL is not set"
  elif [[ "$RUNTIME_SANDBOX_PROVIDER" == "daytona" ]]; then
    local output
    if output=$(probe_daytona_api 2>&1); then
      ok "Daytona API is reachable at $RUNTIME_SANDBOX_DAYTONA_API_URL"
    else
      fail "SANDBOX_PROVIDER=daytona but Daytona API is not reachable. Details: $(printf '%s' "$output" | tail -n 1)"
      return 1
    fi
  else
    ok "Sandbox configuration is acceptable for startup ($RUNTIME_SANDBOX_PROVIDER)"
  fi
}

disable_codex_app_server_workflows_for_startup() {
  local reason="$1"
  export CODEX_APP_SERVER_WORKFLOWS_ENABLED=0
  RUNTIME_CODEX_APP_SERVER_WORKFLOWS_ENABLED=0
  warn "Disabled Codex App Server workflow capabilities for this startup: $reason"
}

validate_codex_app_server_contract() {
  if [[ $RUNTIME_CODEX_APP_SERVER_WORKFLOWS_ENABLED -ne 1 ]]; then
    ok "Codex App Server workflow capabilities are disabled by configuration"
    return 0
  fi

  if [[ "$RUNTIME_ENVIRONMENT" == "production" && $RUNTIME_CODEX_APP_SERVER_SMOKE_VERIFIED -ne 1 ]]; then
    fail "CODEX_APP_SERVER_SMOKE_VERIFIED must be true before enabling Codex App Server workflows in production"
    return 1
  fi

  if [[ "$RUNTIME_SANDBOX_PROVIDER" != "docker" ]]; then
    if [[ $RUNTIME_CODEX_APP_SERVER_SMOKE_VERIFIED -eq 1 ]]; then
      ok "Codex App Server contract is release-smoke verified for $RUNTIME_SANDBOX_PROVIDER sandbox"
    else
      disable_codex_app_server_workflows_for_startup "sandbox provider $RUNTIME_SANDBOX_PROVIDER is not locally probeable; run the codex_smoke suite and set CODEX_APP_SERVER_SMOKE_VERIFIED=true"
    fi
    return 0
  fi

  local output
  if output=$(probe_codex_app_server_image 2>&1); then
    ok "Codex App Server command is available in $RUNTIME_SANDBOX_DOCKER_IMAGE ($RUNTIME_SANDBOX_CODEX_CLI_PACKAGE)"
    return 0
  fi

  disable_codex_app_server_workflows_for_startup "$output"
}

maybe_start_virtual_display() {
  if [[ -n "${DISPLAY:-}" ]]; then
    ok "Using existing display: $DISPLAY"
    return 0
  fi

  if command -v Xvfb >/dev/null 2>&1; then
    info "No DISPLAY detected; starting Xvfb on :99"
    Xvfb :99 -screen 0 1280x720x16 >/tmp/ii-agent-xvfb.log 2>&1 &
    XVFB_PID="$!"
    export DISPLAY=:99
    sleep 1
    if kill -0 "$XVFB_PID" >/dev/null 2>&1; then
      repair "Started Xvfb for headless display support"
      return 0
    fi
    warn "Attempted to start Xvfb, but the process exited immediately"
    XVFB_PID=""
    return 0
  fi

  warn "DISPLAY is unset and Xvfb is unavailable; headless browser features may be limited on this machine"
}

prefix_output() {
  local label="$1"
  local line
  while IFS= read -r line || [[ -n "$line" ]]; do
    printf '[%s] %s\n' "$label" "$line"
  done
}

probe_http_url() {
  local url="$1"
  if command -v curl >/dev/null 2>&1; then
    curl -fsS -o /dev/null "$url" 2>/dev/null
    return $?
  fi

  uv run python - "$url" <<'PY' >/dev/null 2>&1
import sys
from urllib.request import urlopen

with urlopen(sys.argv[1], timeout=2):
    pass
PY
}

wait_for_http_service() {
  local label="$1"
  local url="$2"
  local pid="$3"
  local attempts="${4:-45}"
  local delay_seconds="${5:-1}"
  local try=1

  while ((try <= attempts)); do
    if probe_http_url "$url"; then
      ok "$label is reachable at $url"
      return 0
    fi

    if [[ -n "$pid" ]] && ! kill -0 "$pid" >/dev/null 2>&1; then
      fail "$label exited before becoming reachable at $url"
      return 1
    fi

    sleep "$delay_seconds"
    ((try += 1))
  done

  fail "$label did not become reachable at $url after $((attempts * delay_seconds)) seconds"
  return 1
}

display_host() {
  local host="$1"
  if [[ "$host" == "0.0.0.0" ]]; then
    printf 'localhost'
  else
    printf '%s' "$host"
  fi
}

print_runtime_services() {
  local backend_display_host
  backend_display_host=$(display_host "$SERVER_HOST")

  log ""
  log "Local services:"
  log "  Backend API  : http://${backend_display_host}:${SERVER_PORT}"
  log "  Backend Docs : http://${backend_display_host}:${SERVER_PORT}/docs"
  log "  Backend Health: http://${backend_display_host}:${SERVER_PORT}/health"

  if [[ $BACKEND_ONLY -ne 1 ]]; then
    log "  Frontend     : http://localhost:${FRONTEND_PORT}"
  fi

  if [[ $RUNTIME_DATABASE_IS_LOCAL -eq 1 ]]; then
    log "  PostgreSQL   : ${RUNTIME_DATABASE_URL}"
  fi

  if [[ $RUNTIME_REDIS_ENABLED -eq 1 && $RUNTIME_REDIS_IS_LOCAL -eq 1 ]]; then
    log "  Redis        : ${RUNTIME_REDIS_URL}"
  fi

  if [[ "$RUNTIME_STORAGE_PROVIDER" == "minio" && $RUNTIME_STORAGE_MINIO_IS_LOCAL -eq 1 ]]; then
    log "  MinIO API    : http://${RUNTIME_STORAGE_MINIO_ENDPOINT}"
    case "$RUNTIME_STORAGE_MINIO_ENDPOINT" in
      *:*)
        local minio_host="${RUNTIME_STORAGE_MINIO_ENDPOINT%:*}"
        local minio_port="${RUNTIME_STORAGE_MINIO_ENDPOINT##*:}"
        if [[ "$minio_port" =~ ^[0-9]+$ ]]; then
          log "  MinIO Console: http://${minio_host}:$((minio_port + 1))"
        fi
        ;;
    esac
  fi

  if [[ "$RUNTIME_SANDBOX_PROVIDER" == "daytona" ]]; then
    log "  Daytona API  : ${RUNTIME_SANDBOX_DAYTONA_API_URL}"
  fi
}

start_backend_process() {
  info "Starting backend process"
  (
    cd "$REPO_ROOT" &&
      exec uv run python -m ii_agent.ws_server "${SERVER_ARGS[@]}"
  ) > >(prefix_output "backend") 2>&1 &
  BACKEND_PID="$!"
}

start_frontend_process() {
  if [[ $BACKEND_ONLY -eq 1 ]]; then
    return 0
  fi

  info "Starting frontend process"
  (
    cd "$FRONTEND_DIR" &&
      exec npm run dev -- --host "$FRONTEND_HOST" --port "$FRONTEND_PORT" --strictPort
  ) > >(prefix_output "frontend") 2>&1 &
  FRONTEND_PID="$!"
}

monitor_running_services() {
  while true; do
    if [[ -n "$BACKEND_PID" ]] && ! kill -0 "$BACKEND_PID" >/dev/null 2>&1; then
      wait "$BACKEND_PID"
      return $?
    fi

    if [[ $BACKEND_ONLY -ne 1 && -n "$FRONTEND_PID" ]] && ! kill -0 "$FRONTEND_PID" >/dev/null 2>&1; then
      wait "$FRONTEND_PID"
      return $?
    fi

    sleep 1
  done
}

print_summary() {
  log ""
  log "Preflight summary:"
  log "  Repairs : ${#REPAIRS[@]}"
  log "  Warnings: ${#WARNINGS[@]}"
  log "  Failures: ${#FAILURES[@]}"

  if ((${#REPAIRS[@]})); then
    log ""
    log "Repairs applied:"
    local item
    for item in "${REPAIRS[@]}"; do
      log "  - $item"
    done
  fi

  if ((${#WARNINGS[@]})); then
    log ""
    log "Warnings:"
    local warning_item
    for warning_item in "${WARNINGS[@]}"; do
      log "  - $warning_item"
    done
  fi

  if ((${#FAILURES[@]})); then
    log ""
    log "Blocking failures:"
    local failure_item
    for failure_item in "${FAILURES[@]}"; do
      log "  - $failure_item"
    done
  fi
}

main() {
  cd "$REPO_ROOT"

  parse_args "$@" || return 1
  export II_AGENT_ENV_FILE="$ENV_FILE"
  export DEV_PROJECT_NAME="$COMPOSE_PROJECT_NAME"

  info "Starting II-Agent preflight validation"
  ensure_env_file || true
  ensure_frontend_env_file || true
  load_env_file || true
  load_frontend_env_file || true
  ensure_command "uv" "Install uv from https://astral.sh/uv/" || true

  if ((${#FAILURES[@]})); then
    print_summary
    return 1
  fi

  ensure_uv_environment || true
  ensure_frontend_environment || true
  load_runtime_facts || true
  ensure_local_services_if_needed || true
  ensure_daytona_service_if_needed || true
  validate_llm_config || true
  validate_server_port || true
  validate_frontend_port || true
  validate_database || true
  validate_redis || true
  validate_storage || true
  validate_libmagic || true
  validate_app_import || true
  validate_optional_integrations || true
  validate_codex_app_server_contract || true

  if ((${#FAILURES[@]})); then
    print_summary
    return 1
  fi

  maybe_start_virtual_display
  print_summary

  if [[ $CHECK_ONLY -eq 1 ]]; then
    ok "Preflight passed; check-only mode requested, not starting server"
    return 0
  fi

  cleanup_local_sandbox_containers "startup"

  log ""
  info "All blocking validations passed; starting local development services"
  print_runtime_services
  log ""
  log "Press Ctrl+C to stop all running services."

  start_backend_process
  start_frontend_process
  SERVICES_STARTED=1

  local backend_display_host
  backend_display_host=$(display_host "$SERVER_HOST")
  wait_for_http_service "Backend API" "http://${backend_display_host}:${SERVER_PORT}/health" "$BACKEND_PID"
  if [[ $BACKEND_ONLY -ne 1 ]]; then
    wait_for_http_service "Frontend" "http://localhost:${FRONTEND_PORT}" "$FRONTEND_PID"
  fi

  monitor_running_services
}

main "$@"
