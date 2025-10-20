#!/usr/bin/env bash
set -euo pipefail

OUT="server/tests/results/performance/scalability"
OUTR="$OUT/rest"; OUTG="$OUT/grpc"
mkdir -p "$OUTR" "$OUTG"

if [[ "${1:-}" == "--clean" ]]; then
  rm -f "$OUTR"/*.summary.json "$OUTG"/*.summary.json 2>/dev/null || true
  echo "Cleaned: $OUT"
fi

MODELS=(sigmoid medium_sized_model gpt2_dynamic)
VUS=(1 20 100)
REPS=(1 2 3)
TREND="min,avg,med,p(50),p(90),p(95),p(99),max"
: "${CHECKS_MIN:=0.90}"
: "${REQ_TIMEOUT:=120s}"
: "${REQ_TIMEOUT_E4:=900s}"
: "${MAX_MSG_MB:=256}"

prewarm() {
  local model="$1"
  PREWARM=1 REQ_TIMEOUT="$REQ_TIMEOUT" \
  k6 run -u 1 -d 10s --summary-export /tmp/prewarm_rest.json \
    server/tests/performance/rest/k6_rest.js \
    -e BASE="http://127.0.0.1:8080" -e MODEL_NAME="${model}.onnx" -e USE_FILE=1 || true
  PREWARM=1 REQ_TIMEOUT="$REQ_TIMEOUT" MAX_MSG_MB="$MAX_MSG_MB" \
  k6 run -u 1 -d 10s --summary-export /tmp/prewarm_grpc.json \
    server/tests/performance/grpc/k6_grpc.js \
    -e HOST="127.0.0.1:8080" -e MODEL_NAME="${model}.onnx" -e USE_FILE=1 || true
}

for m in "${MODELS[@]}"; do
  prewarm "$m"
  for r in "${REPS[@]}"; do
    for v in "${VUS[@]}"; do
      TS=$(date -u +%Y%m%d_%H%M%S)

      if (( r % 2 == 1 )); then
        CHECKS_MIN="$CHECKS_MIN" REQ_TIMEOUT="$([ "$v" = "100" ] && echo "$REQ_TIMEOUT_E4" || echo "$REQ_TIMEOUT")" \
        k6 run \
          --summary-export "$OUTR/rest_${m}_v${v}_rep${r}_${TS}.summary.json" \
          --summary-trend-stats "$TREND" \
          server/tests/performance/rest/k6_rest.js \
          -e BASE="http://127.0.0.1:8080" -e MODEL_NAME="${m}.onnx" -e USE_FILE=1 -e VUS="$v"

        CHECKS_MIN="$CHECKS_MIN" REQ_TIMEOUT="$REQ_TIMEOUT" MAX_MSG_MB="$MAX_MSG_MB" \
        k6 run \
          --summary-export "$OUTG/grpc_${m}_v${v}_rep${r}_${TS}.summary.json" \
          --summary-trend-stats "$TREND" \
          server/tests/performance/grpc/k6_grpc.js \
          -e HOST="127.0.0.1:8080" -e MODEL_NAME="${m}.onnx" -e USE_FILE=1 -e VUS="$v"
      else
        CHECKS_MIN="$CHECKS_MIN" REQ_TIMEOUT="$REQ_TIMEOUT" MAX_MSG_MB="$MAX_MSG_MB" \
        k6 run \
          --summary-export "$OUTG/grpc_${m}_v${v}_rep${r}_${TS}.summary.json" \
          --summary-trend-stats "$TREND" \
          server/tests/performance/grpc/k6_grpc.js \
          -e HOST="127.0.0.1:8080" -e MODEL_NAME="${m}.onnx" -e USE_FILE=1 -e VUS="$v"

        CHECKS_MIN="$CHECKS_MIN" REQ_TIMEOUT="$([ "$v" = "100" ] && echo "$REQ_TIMEOUT_E4" || echo "$REQ_TIMEOUT")" \
        k6 run \
          --summary-export "$OUTR/rest_${m}_v${v}_rep${r}_${TS}.summary.json" \
          --summary-trend-stats "$TREND" \
          server/tests/performance/rest/k6_rest.js \
          -e BASE="http://127.0.0.1:8080" -e MODEL_NAME="${m}.onnx" -e USE_FILE=1 -e VUS="$v"
      fi
    done
  done
done
echo "E4 complete → $OUT"
