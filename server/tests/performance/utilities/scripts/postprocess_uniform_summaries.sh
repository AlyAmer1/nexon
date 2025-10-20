#!/usr/bin/env bash
set -euo pipefail
export LC_ALL=C

# All latency values emitted in **milliseconds**.
BASE="${1:-server/tests/results/performance}"

# REST: http_req_duration is in ms in k6 summaries
rest_pct_ms(){ jq -r --arg k "$2" '
  (.metrics.http_req_duration["p(" + $k + ")"]
   // .metrics.http_req_duration.percentiles[$k] // 0)
' "$1"; }
rest_agg_ms(){ jq -r --arg key "$2" '
  (.metrics.http_req_duration[$key] // 0)
' "$1"; }

# gRPC: prefer grpc_req_duration (ms). Fallback to rpc_duration_ms (also ms).
grpc_pct_ms(){ jq -r --arg k "$2" '
  (.metrics.grpc_req_duration["p(" + $k + ")"]
   // .metrics.grpc_req_duration.percentiles[$k]
   // .metrics.rpc_duration_ms["p(" + $k + ")"]
   // .metrics.rpc_duration_ms.percentiles[$k] // 0)
' "$1"; }
grpc_agg_ms(){ jq -r --arg key "$2" '
  (.metrics.grpc_req_duration[$key]
   // .metrics.rpc_duration_ms[$key] // 0)
' "$1"; }

mk_csv(){
  local bucket="$1" proto="$2"
  local dir="$BASE/$bucket/$proto"
  [ -d "$dir" ] || { echo "skip: $dir"; return; }

  local out="$BASE/$bucket/${bucket}_${proto}.csv"
  tmp="$(mktemp)"
  echo "bucket,proto,file,model,vu,rep,arm,run_ts,p50_ms,p95_ms,p99_ms,avg_ms,min_ms,max_ms,iterations,iter_rate" > "$tmp"

  shopt -s nullglob
  for f in "$dir"/*.summary.json; do
    bn=$(basename "$f")

    # Normalize model short-name
    model=$(echo "$bn" | sed -E 's/^(rest_|grpc_)//; s/_v[0-9]+.*//; s/.*_(sigmoid|medium_sized_model|gpt2_dynamic).*/\1/; s/medium_sized_model/medium/; s/gpt2_dynamic/gpt2/')
    [[ "$bn" =~ _v([0-9]+)_ ]] && vu="${BASH_REMATCH[1]}" || vu="1"
    [[ "$bn" =~ _rep([0-9]+)_ ]] && rep="${BASH_REMATCH[1]}" || rep=""
    [[ "$bn" =~ E2_(gRPC|REST)_([a-z_]+)_rep ]] && arm="${BASH_REMATCH[2]}" || arm=""
    ts=$(echo "$bn" | sed -E 's/.*_([0-9]{8}_[0-9]{6}).*/\1/')

    if [ "$proto" = "rest" ]; then
      p50=$(rest_pct_ms "$f" "50"); p95=$(rest_pct_ms "$f" "95"); p99=$(rest_pct_ms "$f" "99")
      avg=$(rest_agg_ms "$f" "avg"); min=$(rest_agg_ms "$f" "min"); max=$(rest_agg_ms "$f" "max")
    else
      p50=$(grpc_pct_ms "$f" "50"); p95=$(grpc_pct_ms "$f" "95"); p99=$(grpc_pct_ms "$f" "99")
      avg=$(grpc_agg_ms "$f" "avg"); min=$(grpc_agg_ms "$f" "min"); max=$(grpc_agg_ms "$f" "max")
    fi

    iters=$(jq -r '(.metrics.iterations.count // 0)' "$f")
    rate=$(jq -r '(.metrics.iterations.rate // 0)' "$f")

    printf '%s,%s,%s,%s,%s,%s,%s,%s,%.3f,%.3f,%.3f,%.3f,%.3f,%.3f,%s,%.9g\n' \
      "$bucket" "$proto" "$bn" "$model" "$vu" "$rep" "$arm" "$ts" \
      "${p50:-0}" "${p95:-0}" "${p99:-0}" "${avg:-0}" "${min:-0}" "${max:-0}" \
      "$iters" "$rate" >> "$tmp"
  done

  mv "$tmp" "$out"
  echo "wrote $out"
}

for b in latency_throughput overhead scalability; do
  for p in rest grpc; do mk_csv "$b" "$p"; done
done
