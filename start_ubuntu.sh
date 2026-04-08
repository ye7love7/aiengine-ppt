#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

HOST="${PPT_SERVICE_HOST:-0.0.0.0}"
PORT="${PPT_SERVICE_PORT:-8000}"
LOG_DIR="${PPT_SERVICE_LOG_DIR:-$ROOT_DIR/runtime}"
PID_FILE="${PPT_SERVICE_PID_FILE:-$LOG_DIR/service_api.pid}"
LOG_FILE="${PPT_SERVICE_LOG_FILE:-$LOG_DIR/service_api.log}"
MODE="background"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --foreground)
      MODE="foreground"
      shift
      ;;
    --background)
      MODE="background"
      shift
      ;;
    --help|-h)
      cat <<EOF
Usage: ./start_ubuntu.sh [--foreground|--background]

Defaults:
  host: $HOST
  port: $PORT
  log:  $LOG_FILE
  pid:  $PID_FILE
EOF
      exit 0
      ;;
    *)
      echo "[ERROR] Unknown argument: $1"
      exit 1
      ;;
  esac
done

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 is not available in PATH."
  exit 1
fi

if ! python3 -c "import uvicorn" >/dev/null 2>&1; then
  echo "[ERROR] uvicorn is not installed in the current Python environment."
  exit 1
fi

mkdir -p "$LOG_DIR"

if [[ -f "$PID_FILE" ]]; then
  EXISTING_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
  if [[ -n "$EXISTING_PID" ]] && kill -0 "$EXISTING_PID" >/dev/null 2>&1; then
    echo "[ERROR] Service already running with PID $EXISTING_PID"
    echo "[INFO] Log file: $LOG_FILE"
    exit 1
  fi
  rm -f "$PID_FILE"
fi

echo "[INFO] Starting Offline PPT Master service ..."
echo "[INFO] Open: http://127.0.0.1:${PORT}/frontend"

if [[ "$MODE" == "foreground" ]]; then
  python3 -m uvicorn service_api.main:app --host "$HOST" --port "$PORT"
  exit 0
fi

nohup python3 -m uvicorn service_api.main:app --host "$HOST" --port "$PORT" >>"$LOG_FILE" 2>&1 &
SERVICE_PID=$!
echo "$SERVICE_PID" >"$PID_FILE"

echo "[INFO] Service started in background."
echo "[INFO] PID: $SERVICE_PID"
echo "[INFO] Log: $LOG_FILE"
