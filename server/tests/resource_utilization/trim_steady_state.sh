#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RAW_R="$ROOT/server/tests/results/resource_utilization/raw/rest"
RAW_G="$ROOT/server/tests/results/resource_utilization/raw/grpc"
ST_R="$ROOT/server/tests/results/resource_utilization/steady/rest"
ST_G="$ROOT/server/tests/results/resource_utilization/steady/grpc"
mkdir -p "$ST_R" "$ST_G"

filter() {
  local src="$1" dst="$2"
  awk -F, 'FNR==NR{ if(FNR>1) c[$1]++; next } FNR==1{print; next} c[$1]==3' "$src" "$src" > "$dst.tmp"
  mv "$dst.tmp" "$dst"
}

shopt -s nullglob
for raw in "$RAW_R"/*.csv; do
  base="$(basename "$raw")"
  filter "$raw" "$ST_R/${base%.csv}.steady.csv"
done
for raw in "$RAW_G"/*.csv; do
  base="$(basename "$raw")"
  filter "$raw" "$ST_G/${base%.csv}.steady.csv"
done
echo "STEADY built."
