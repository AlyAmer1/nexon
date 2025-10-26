#!/usr/bin/env bash
set -euo pipefail

command -v jq >/dev/null || { echo "ERROR: jq is required"; exit 1; }

BASE="${BASE:-server/tests/results/performance}"

if [[ "${1:-}" == "--clean" ]]; then
  rm -rf "$BASE/bandwidth"
fi

mkdir -p "$BASE/bandwidth/rest" "$BASE/bandwidth/grpc"

# Sources that are scanned (both structured E1 and flat)
REST_DIRS=(
  "$BASE/latency_throughput/rest"
  "$BASE/rest"
)
GRPC_DIRS=(
  "$BASE/latency_throughput/grpc"
  "$BASE/grpc"
)

echo "Scanning REST in: ${REST_DIRS[*]}"
echo "Scanning gRPC in: ${GRPC_DIRS[*]}"

CSV_R="$BASE/bandwidth/E2_bandwidth_rest.csv"
CSV_G="$BASE/bandwidth/E2_bandwidth_grpc.csv"
echo "proto,model,run_ts,recv_MBps,sent_MBps,recv_GB,sent_GB" > "$CSV_R"
echo "proto,model,run_ts,recv_MBps,sent_MBps,recv_GB,sent_GB" > "$CSV_G"

process_dir() {
  local proto="$1" outdir="$2" csv="$3"; shift 3
  local count=0
  for src in "$@"; do
    [ -d "$src" ] || continue
    # Use find -print0 for safety (filenames with spaces)
    while IFS= read -r -d '' f; do
      bn="$(basename "$f")"
      base="${bn%.summary.json}"

      # best-effort model + timestamp from filename
      # model: first token that looks like onnx/gpt2/sigmoid/medium
      model="$(printf "%s" "$base" | tr '_' '\n' | grep -E 'onnx|gpt2|sigmoid|medium' | head -n1 || true)"
      [ -n "${model:-}" ] || model="unknown_model"

      # timestamp: last YYYYMMDD_HHMMSS
      ts="$(printf "%s" "$base" | grep -Eo '[0-9]{8}_[0-9]{6}' | tail -n1 || true)"
      [ -n "${ts:-}" ] || ts="unknown_ts"

      # per-run JSON
      jq -c --arg p "$proto" --arg m "$model" --arg t "$ts" '{
        proto: $p, model: $m, run_ts: $t,
        recv_MBps: ((.metrics.data_received.rate // 0)/1048576),
        sent_MBps: ((.metrics.data_sent.rate     // 0)/1048576),
        recv_GB:   ((.metrics.data_received.count // 0)/1073741824),
        sent_GB:   ((.metrics.data_sent.count     // 0)/1073741824)
      }' "$f" > "$outdir/${base}.bandwidth.json"

      # Append CSV row
      jq -r --arg p "$proto" --arg m "$model" --arg t "$ts" '
        [$p,$m,$t,
         ((.metrics.data_received.rate // 0)/1048576),
         ((.metrics.data_sent.rate     // 0)/1048576),
         ((.metrics.data_received.count // 0)/1073741824),
         ((.metrics.data_sent.count     // 0)/1073741824)
        ] | @csv' "$f" >> "$csv"

      count=$((count+1))
    done < <(find "$src" -type f -name '*.summary.json' -print0 2>/dev/null)
  done
  echo "$count"
}

echo
echo "Generating REST bandwidth…"
rest_count="$(process_dir "REST" "$BASE/bandwidth/rest" "$CSV_R" "${REST_DIRS[@]}")"
echo "REST: wrote $rest_count per-run JSON files"
echo "REST CSV → $CSV_R"

echo
echo "Generating gRPC bandwidth…"
grpc_count="$(process_dir "gRPC" "$BASE/bandwidth/grpc" "$CSV_G" "${GRPC_DIRS[@]}")"
echo "gRPC: wrote $grpc_count per-run JSON files"
echo "gRPC CSV → $CSV_G"

echo
echo "== Done =="
echo "REST per-run: $(ls -1 "$BASE/bandwidth/rest/"*.bandwidth.json 2>/dev/null | wc -l)"
echo "gRPC per-run: $(ls -1 "$BASE/bandwidth/grpc/"*.bandwidth.json 2>/dev/null | wc -l)"
