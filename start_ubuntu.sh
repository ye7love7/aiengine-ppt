#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] python3 is not available in PATH."
  exit 1
fi

if ! python3 -c "import uvicorn" >/dev/null 2>&1; then
  echo "[ERROR] uvicorn is not installed in the current Python environment."
  exit 1
fi

cat <<'EOF'
[INFO] Starting Offline PPT Master service ...
[INFO] Open: http://127.0.0.1:8000/frontend
EOF

python3 -m uvicorn service_api.main:app --host 0.0.0.0 --port 8000
