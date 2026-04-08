#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${PPT_SERVICE_LOG_DIR:-$ROOT_DIR/runtime}"
PID_FILE="${PPT_SERVICE_PID_FILE:-$LOG_DIR/service_api.pid}"

if [[ ! -f "$PID_FILE" ]]; then
  echo "[INFO] No PID file found. Service may already be stopped."
  exit 0
fi

SERVICE_PID="$(cat "$PID_FILE" 2>/dev/null || true)"
if [[ -z "$SERVICE_PID" ]]; then
  echo "[INFO] PID file is empty. Removing stale PID file."
  rm -f "$PID_FILE"
  exit 0
fi

if kill -0 "$SERVICE_PID" >/dev/null 2>&1; then
  kill "$SERVICE_PID"
  echo "[INFO] Stopped service PID $SERVICE_PID"
else
  echo "[INFO] Process $SERVICE_PID is not running. Removing stale PID file."
fi

rm -f "$PID_FILE"
