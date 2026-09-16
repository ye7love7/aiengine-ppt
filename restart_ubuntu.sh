#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"
if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  echo "Usage: ./restart_ubuntu.sh [--foreground|--background]"
  exit 0
fi
if [[ $# -gt 1 || ( $# -eq 1 && "$1" != "--foreground" && "$1" != "--background" ) ]]; then
  echo "[ERROR] Unknown arguments. Use --foreground or --background."
  exit 1
fi
echo "[INFO] Stopping service ..."
"$ROOT_DIR/stop_ubuntu.sh"
echo "[INFO] Starting service ..."
"$ROOT_DIR/start_ubuntu.sh" "$@"
