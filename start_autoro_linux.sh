#!/usr/bin/env bash
set -u

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DRIVE_ROOT="$APP_DIR"
DATABASE_PATH="$DRIVE_ROOT/runtime/Database/autoro.db"
HOST="${AUTORO_HOST:-127.0.0.1}"
PORT="${AUTORO_PORT:-8000}"
URL="http://$HOST:$PORT"
LOG_DIR="$APP_DIR/runtime/logs"
PID_FILE="$APP_DIR/.autoro-linux.pid"

case "$HOST" in
  127.0.0.1|localhost) ;;
  *)
    echo "AutoRO supports loopback-only operation."
    echo "Refusing AUTORO_HOST=$HOST. Use 127.0.0.1 or localhost."
    exit 1
    ;;
esac

find_python() {
  if [ -n "${AUTORO_PYTHON:-}" ] && command -v "$AUTORO_PYTHON" >/dev/null 2>&1; then
    command -v "$AUTORO_PYTHON"
    return 0
  fi
  if [ -x "$APP_DIR/.venv/bin/python" ]; then
    echo "$APP_DIR/.venv/bin/python"
    return 0
  fi
  if command -v python3 >/dev/null 2>&1; then
    command -v python3
    return 0
  fi
  if command -v python >/dev/null 2>&1; then
    command -v python
    return 0
  fi
  return 1
}

port_ready() {
  "$PYTHON_EXE" - "$HOST" "$PORT" <<'PY'
import socket
import sys

host = sys.argv[1]
port = int(sys.argv[2])
sock = socket.socket()
sock.settimeout(1)
try:
    sys.exit(0 if sock.connect_ex((host, port)) == 0 else 1)
finally:
    sock.close()
PY
}

model_ready() {
  "$PYTHON_EXE" - <<'PY'
import sys
import urllib.error
import urllib.request

try:
    with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=2) as response:
        sys.exit(0 if 200 <= response.status < 300 else 1)
except (urllib.error.URLError, TimeoutError, OSError):
    sys.exit(1)
PY
}

open_browser() {
  mkdir -p "$LOG_DIR"
  local browser_log="$LOG_DIR/browser_open_$(date +%Y%m%d_%H%M%S).log"
  echo "Opening: $URL"
  if command -v xdg-open >/dev/null 2>&1; then
    if xdg-open "$URL" >"$browser_log" 2>&1; then
      echo "Browser launch request sent."
      return 0
    fi
  fi
  if command -v gio >/dev/null 2>&1; then
    if gio open "$URL" >"$browser_log" 2>&1; then
      echo "Browser launch request sent."
      return 0
    fi
  fi
  echo "AutoRO could not open the browser automatically."
  echo "Open this URL manually:"
  echo "  $URL"
  echo "Browser error log:"
  echo "  $browser_log"
  return 1
}

pause_if_interactive() {
  if [ -t 0 ]; then
    echo
    read -r -p "Press Enter to close this launcher..." _autoro_pause || true
  fi
}

echo "AutoRO Linux launcher"
echo

PYTHON_EXE="$(find_python || true)"
if [ -z "$PYTHON_EXE" ]; then
  echo "AutoRO could not find Python on Linux."
  echo "Install python3, or set AUTORO_PYTHON=/path/to/python."
  exit 1
fi

cd "$APP_DIR" || exit 1

if [ ! -f "$DATABASE_PATH" ]; then
  echo "AutoRO database was not found. Initializing:"
  echo "  $DATABASE_PATH"
  mkdir -p "$(dirname "$DATABASE_PATH")"
  if ! "$PYTHON_EXE" -c "from app.database import init_db, DB_PATH; init_db(); print(DB_PATH)" >/dev/null 2>&1; then
    echo "AutoRO could not initialize the database."
    exit 1
  fi
fi

if ! "$PYTHON_EXE" -c "import fastapi, jinja2, uvicorn, reportlab, PIL" >/dev/null 2>&1; then
  echo "AutoRO Python dependencies are missing for: $PYTHON_EXE"
  echo "Automatically configuring local virtual environment..."

  if [ ! -d "$APP_DIR/.venv" ]; then
    "$PYTHON_EXE" -m venv "$APP_DIR/.venv"
  fi

  # Ensure we use the new venv's python executable
  VENV_PYTHON="$APP_DIR/.venv/bin/python"

  echo "Installing dependencies strictly from on-board Wheelhouse..."
  if "$VENV_PYTHON" -m pip install --no-index --find-links="$APP_DIR/Tools/Wheelhouse_Linux" -r "$APP_DIR/requirements.txt"; then
    echo "Dependencies installed successfully!"
    PYTHON_EXE="$VENV_PYTHON"
  else
    echo "Failed to install dependencies offline."
    echo "Please ensure Tools/Wheelhouse_Linux is populated with the required packages."
    exit 1
  fi
fi

if ! command -v pdftotext >/dev/null 2>&1; then
  echo "AutoRO PDF text extraction dependency is missing:"
  echo "  pdftotext"
  echo
  echo "Install poppler-utils before using estimate conversion."
  exit 1
fi

if [ "${1:-}" = "--check" ]; then
  echo "Python: $PYTHON_EXE"
  echo "Database: $DATABASE_PATH"
  echo "Dependencies: OK"
  echo "PDF extraction: $(command -v pdftotext)"
  echo "URL: $URL"
  exit 0
fi

if port_ready; then
  echo "AutoRO is already responding at $URL."
  echo "The existing AutoRO session is healthy; a second copy was not started."
  open_browser || true
  pause_if_interactive
  exit 0
fi

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/autoro_$(date +%Y%m%d_%H%M%S).log"

echo "Starting shared Qwen model..."
"$APP_DIR/Llamafile/start_model_linux.sh" > "$LOG_DIR/qwen_$(date +%Y%m%d_%H%M%S).log" 2>&1 &
MODEL_PID=$!

echo "Starting AutoRO server..."
echo "Python:"
echo "  $PYTHON_EXE"
echo "Log:"
echo "  $LOG_FILE"
echo

"$PYTHON_EXE" -m uvicorn app.main:app --host "$HOST" --port "$PORT" >"$LOG_FILE" 2>&1 &
SERVER_PID=$!
echo "$SERVER_PID" > "$PID_FILE"

cleanup() {
  echo
  if kill -0 "$SERVER_PID" >/dev/null 2>&1; then
    echo "Stopping AutoRO server..."
    kill "$SERVER_PID" >/dev/null 2>&1 || true
  fi
  if kill -0 "$MODEL_PID" >/dev/null 2>&1; then
    echo "Stopping shared Qwen model..."
    kill -TERM "$MODEL_PID" >/dev/null 2>&1 || true
  fi
}
trap cleanup INT TERM

echo "Waiting for AutoRO to become ready ..."
app_ready=0
model_is_ready=0
browser_opened=0
for _ in $(seq 1 120); do
  if [ "$app_ready" -eq 0 ] && port_ready; then
    app_ready=1
    echo "AutoRO web app is ready. Opening browser while the Qwen model finishes loading..."
    if open_browser; then
      browser_opened=1
    fi
  fi
  if model_ready; then
    model_is_ready=1
  fi
  if [ "$app_ready" -eq 1 ] && [ "$model_is_ready" -eq 1 ]; then
    break
  fi
  sleep 1
done

if [ "$app_ready" -ne 1 ]; then
  echo
  echo "AutoRO did not become ready."
  echo "Recent server log:"
  tail -40 "$LOG_FILE" 2>/dev/null || true
  cleanup
  exit 1
fi

if [ "$model_is_ready" -eq 1 ]; then
  echo "Shared Qwen model is ready."
else
  echo "Shared Qwen model is still loading or offline after 120 seconds."
  echo "AutoRO remains open; model-dependent tools will show their current status."
fi
if [ "$browser_opened" -eq 0 ]; then
  open_browser || true
fi
echo
echo "Keep this terminal open while using AutoRO."
echo "Press Ctrl+C here to stop the AutoRO server."
wait "$SERVER_PID"
