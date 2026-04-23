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
RUNTIME_SANDBOX_READY=1

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
  set -a
  # shellcheck disable=SC1090
  if . "$ENV_FILE"; then
    set +a
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
  if [[ "$RUNTIME_SANDBOX_PROVIDER" == "e2b" && $RUNTIME_SANDBOX_READY -ne 1 ]]; then
    warn "SANDBOX_PROVIDER=e2b but SANDBOX_E2B_API_KEY is not set; sandbox features will fail at runtime"
  else
    ok "Sandbox configuration is acceptable for startup ($RUNTIME_SANDBOX_PROVIDER)"
  fi
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
  validate_llm_config || true
  validate_server_port || true
  validate_frontend_port || true
  validate_database || true
  validate_redis || true
  validate_storage || true
  validate_libmagic || true
  validate_app_import || true
  validate_optional_integrations || true

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
