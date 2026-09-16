#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${PPT_SERVICE_LOG_DIR:-$ROOT_DIR/runtime}"
LOG_FILE="${PPT_SERVICE_LOG_FILE:-$LOG_DIR/service_api.log}"
JOBS_DIR="${PPT_SERVICE_JOBS_DIR:-$ROOT_DIR/service_data/jobs}"
LINES=80; FOLLOW=0; JOB_ID=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --lines|-n) [[ $# -ge 2 ]] || { echo "[ERROR] Missing value for $1"; exit 1; }; LINES="$2"; shift 2 ;;
    --follow|-f) FOLLOW=1; shift ;;
    --job) [[ $# -ge 2 ]] || { echo "[ERROR] Missing task id"; exit 1; }; JOB_ID="$2"; shift 2 ;;
    --help|-h) echo "Usage: ./logs_ubuntu.sh [--lines N] [--follow] [--job TASK_ID]"; exit 0 ;;
    *) echo "[ERROR] Unknown argument: $1"; exit 1 ;;
  esac
done
[[ "$LINES" =~ ^[0-9]+$ && "$LINES" -gt 0 ]] || { echo "[ERROR] --lines must be a positive integer"; exit 1; }
if [[ -n "$JOB_ID" ]]; then
  [[ "$JOB_ID" != *"/"* && "$JOB_ID" != *"\\"* && "$JOB_ID" != *".."* ]] || { echo "[ERROR] Unsafe task id: $JOB_ID"; exit 1; }
  TARGET="$JOBS_DIR/$JOB_ID/run.log"
else
  TARGET="$LOG_FILE"
fi
if [[ ! -f "$TARGET" ]]; then echo "[WARN] Log file not found: $TARGET"; echo "[INFO] No log files available yet."; exit 0; fi
if [[ "$FOLLOW" -eq 1 ]]; then tail -n "$LINES" -f "$TARGET"; else tail -n "$LINES" "$TARGET"; fi
