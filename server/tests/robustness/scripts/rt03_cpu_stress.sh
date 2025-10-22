#!/usr/bin/env bash
set -euo pipefail

DUR="${DUR:-60}"
LOAD="${LOAD:-80}"         # percent
CPU_WORKERS="${CPU_WORKERS:-0}"  # 0 = one per core
OS="$(uname -s)"

if ! command -v stress-ng >/dev/null 2>&1; then
  if [[ "$OS" == "Darwin" ]]; then
    echo "[RT03] Installing stress-ng via Homebrew..."
    brew list stress-ng >/dev/null 2>&1 || brew install stress-ng
  else
    echo "[RT03] Installing stress-ng (sudo required)..."
    sudo apt-get update -y && sudo apt-get install -y stress-ng
  fi
fi

echo "[RT03] stress-ng --cpu ${CPU_WORKERS} --cpu-load ${LOAD}% --timeout ${DUR}s"
stress-ng --cpu "$CPU_WORKERS" --cpu-load "$LOAD" --timeout "${DUR}s"
echo "[RT03] Done."
