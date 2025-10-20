#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
RAW_R="$ROOT/server/tests/results/resource_utilization/raw/rest"
RAW_G="$ROOT/server/tests/results/resource_utilization/raw/grpc"
ST_R="$ROOT/server/tests/results/resource_utilization/steady/rest"
ST_G="$ROOT/server/tests/results/resource_utilization/steady/grpc"
SUM="$ROOT/server/tests/results/resource_utilization/summary"

CLEAN=0
[[ "${1:-}" == "--clean" ]] && CLEAN=1

if (( CLEAN )); then
  rm -rf "$RAW_R" "$RAW_G" "$ST_R" "$ST_G" "$SUM"
fi

mkdir -p "$RAW_R" "$RAW_G" "$ST_R" "$ST_G" "$SUM"

# Prefer your orchestrator if present
if [ -x "$ROOT/server/tests/resource_utilization/run_ru_all.sh" ]; then
  bash "$ROOT/server/tests/resource_utilization/run_ru_all.sh"
elif [ -x "$ROOT/server/tests/resource_utilization/run_resource_utilization.sh" ]; then
  bash "$ROOT/server/tests/resource_utilization/run_resource_utilization.sh"
else
  echo "ERROR: No capture runner found (run_ru_all.sh / run_resource_utilization.sh)"; exit 1
fi

# Ensure strict 3-rows-per-timestamp in STEADY
if [ -x "$ROOT/server/tests/resource_utilization/trim_steady_state.sh" ]; then
  bash "$ROOT/server/tests/resource_utilization/trim_steady_state.sh"
else
  for raw in "$RAW_R"/*.csv "$RAW_G"/*.csv; do
    [ -e "$raw" ] || continue
    base="$(basename "$raw")"
    if [[ "$raw" == *"/raw/rest/"* ]]; then
      dst="$ST_R/${base%.csv}.steady.csv"
    else
      dst="$ST_G/${base%.csv}.steady.csv"
    fi
    awk -F, 'FNR==NR{ if(FNR>1) c[$1]++; next } FNR==1{print; next} c[$1]==3' "$raw" "$raw" > "$dst.tmp"
    mv "$dst.tmp" "$dst"
  done
fi

echo "OK: RU capture + steady filtering complete."
