#!/usr/bin/env bash
set -euo pipefail
DUR="${1:-180}"                      # seconds
OUT="${2:-container_stats.csv}"
NAMES="${3:-envoy rest grpc}"        # adjust if your compose names differ

echo "timestamp,container,cpu_perc,mem_perc" > "$OUT"
for ((sec=0; sec<DUR; sec++)); do
  TS="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  docker stats --no-stream --format '{{.Name}},{{.CPUPerc}},{{.MemPerc}}' ${NAMES} 2>/dev/null \
  | while IFS=, read -r name cpu mem; do
      echo "${TS},${name},${cpu%\%},${mem%\%}" >> "$OUT"
    done
  sleep 1
done
echo "Wrote $OUT"
