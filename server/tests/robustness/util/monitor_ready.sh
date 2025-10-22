#!/usr/bin/env bash
set -euo pipefail

BASE="${BASE:-http://127.0.0.1:8080}"
# Note: OUTDIR is now expected to be passed in by the runbook
OUTDIR="${OUTDIR:-server/tests/results/robustness}"
TS="$(date -u +%Y%m%d_%H%M%S)"
LOG="${OUTDIR}/READY_MONITOR_${TS}.log"
SUM="${OUTDIR}/READY_MONITOR_${TS}.summary.txt"

mkdir -p "$OUTDIR"

echo "[MON] Polling ${BASE}/readyz (1Hz). Log: $LOG"
down_at=""
up_at=""
state="up"

while true; do
  now="$(date -u +%s)"
  if curl -fsS "${BASE}/readyz" >/dev/null 2>&1; then
    if [[ "$state" == "down" ]]; then
      up_at="$now"
      dt=$(( up_at - down_at ))
      echo "UP @ ${up_at} (downtime ${dt}s)" | tee -a "$LOG"
      echo "downtime_seconds=${dt}" > "$SUM"
      exit 0
    fi
  else
    if [[ "$state" == "up" ]]; then
      down_at="$now"
      echo "DOWN @ ${down_at}" | tee -a "$LOG"
      state="down"
    fi
  fi
  sleep 1
done
