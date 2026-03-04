#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV_ACTIVATE="${ROOT_DIR}/../.venv/bin/activate"
HOST="${HOST:-127.0.0.1}"
PORT="${PORT:-18000}"
BASE_URL="${BASE_URL:-http://${HOST}:${PORT}}"
HEALTH_TIMEOUT_SECONDS="${HEALTH_TIMEOUT_SECONDS:-25}"

if [[ ! -f "${VENV_ACTIVATE}" ]]; then
  echo "Virtualenv not found: ${VENV_ACTIVATE}" >&2
  exit 1
fi

source "${VENV_ACTIVATE}"
cd "${ROOT_DIR}"

./scripts/generate_openapi_code.sh >/dev/null

cleanup() {
  if [[ -n "${SERVER_PID:-}" ]] && kill -0 "${SERVER_PID}" 2>/dev/null; then
    kill "${SERVER_PID}" >/dev/null 2>&1 || true
    wait "${SERVER_PID}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

wait_health() {
  local ready=0
  for ((i=0; i<HEALTH_TIMEOUT_SECONDS; i++)); do
    if curl -fsS "${BASE_URL}/health" >/dev/null 2>&1; then
      ready=1
      break
    fi
    sleep 1
  done
  if [[ "$ready" -ne 1 ]]; then
    echo "API is not healthy at ${BASE_URL}/health" >&2
    echo "--- uvicorn log ---" >&2
    tail -n 100 "${UVICORN_LOG}" >&2 || true
    exit 1
  fi
}

start_server() {
  local db_file="$1"
  local order_limit="$2"
  UVICORN_LOG="/tmp/task2_all_tests_uvicorn_${order_limit}.log"
  : > "${UVICORN_LOG}"
  DATABASE_URL="sqlite+pysqlite:///./${db_file}" DB_FILE="${db_file}" python - <<'PY'
import os
import app

db_file = os.environ.get("DB_FILE")
if db_file and os.path.exists(db_file):
    os.remove(db_file)
if db_file and os.path.exists(f"{db_file}-wal"):
    os.remove(f"{db_file}-wal")
if db_file and os.path.exists(f"{db_file}-shm"):
    os.remove(f"{db_file}-shm")

app.Base.metadata.create_all(bind=app.engine)
print("schema ready")
PY
  DATABASE_URL="sqlite+pysqlite:///./${db_file}" \
  ORDER_LIMIT_MINUTES="${order_limit}" \
  JWT_SECRET="test-secret" \
  uvicorn app:app --host "${HOST}" --port "${PORT}" >"${UVICORN_LOG}" 2>&1 &
  SERVER_PID=$!
  wait_health
}

run_pytest() {
  echo "[1/5] Running pytest..."
  python -m pytest -q
}

run_main_e2e() {
  echo "[2/5] Running full E2E scenarios A-H..."
  BASE_URL="${BASE_URL}" python tests/e2e_main_scenarios.py
}

run_additional_e2e() {
  echo "[3/5] Running additional E2E scenarios..."
  BASE_URL="${BASE_URL}" python tests/e2e_additional_scenarios.py
}

check_logs_and_db_proof() {
  echo "[4/5] Verifying logs (H) and printing DB proof (I)..."
  UVICORN_LOG="${UVICORN_LOG}" python tests/check_logs_and_db_proof.py
}

run_rate_limit_checks() {
  echo "[5/5] Running ORDER_LIMIT_EXCEEDED checks..."

  cleanup
  start_server "scenario_all_rate.db" "5"

  BASE_URL="${BASE_URL}" python tests/e2e_rate_limit.py
}

run_pytest
start_server "scenario_all_main.db" "0"
run_main_e2e
run_additional_e2e
check_logs_and_db_proof
run_rate_limit_checks

echo "All tests passed (pytest + full e2e + additional e2e + logs + db proof + rate-limit)"
