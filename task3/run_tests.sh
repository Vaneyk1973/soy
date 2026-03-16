#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if [ ! -f requirements.txt ]; then
  echo "requirements.txt not found" >&2
  exit 1
fi

if [ -x "$ROOT_DIR/../.venv/bin/python" ]; then
  PYTHON_BIN="$ROOT_DIR/../.venv/bin/python"
else
  PYTHON_BIN="python3"
fi

"$PYTHON_BIN" -m pip install -r requirements.txt

if command -v pytest >/dev/null 2>&1; then
  PYTEST_BIN="pytest"
else
  PYTEST_BIN="$PYTHON_BIN -m pytest"
fi

if docker compose ps >/dev/null 2>&1 || docker-compose ps >/dev/null 2>&1; then
  if (docker compose ps >/dev/null 2>&1 && ! docker compose ps --services --filter "status=running" | grep -q .) || \
     (docker-compose ps >/dev/null 2>&1 && ! docker-compose ps --services --filter "status=running" | grep -q .); then
    echo "Docker services are not running. Start with: docker-compose up --build" >&2
    exit 1
  fi
  "$PYTHON_BIN" - <<'PY'
import socket
import time

def wait(host, port, timeout=30):
    end = time.time() + timeout
    while time.time() < end:
        try:
            with socket.create_connection((host, port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False

if not wait("127.0.0.1", 50051, 30):
    raise SystemExit("gRPC service not ready on 50051")
if not wait("127.0.0.1", 8000, 30):
    raise SystemExit("Booking service not ready on 8000")
PY
  $PYTEST_BIN
else
  echo "Docker Compose not available. Unable to run full test suite." >&2
  exit 1
fi
