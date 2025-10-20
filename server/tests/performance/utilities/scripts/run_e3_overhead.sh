#!/usr/bin/env bash
set -euo pipefail

OUT="server/tests/results/performance/overhead"
OUTR="$OUT/rest"; OUTG="$OUT/grpc"
mkdir -p "$OUTR" "$OUTG"

if [[ "${1:-}" == "--clean" ]]; then
  rm -f "$OUTR"/*.summary.json "$OUTG"/*.summary.json 2>/dev/null || true
  echo "Cleaned: $OUT"
fi

MODEL="sigmoid.onnx"
VUS=1
REPS=(1 2 3)
TREND="min,avg,med,p(50),p(90),p(95),p(99),max"
: "${CHECKS_MIN:=0.90}"
: "${REQ_TIMEOUT:=120s}"
: "${MAX_MSG_MB:=256}"

# Endpoints
ENVOY_REST_BASE="${ENVOY_REST_BASE:-http://127.0.0.1:8080}"
ENVOY_GRPC_HOST="${ENVOY_GRPC_HOST:-127.0.0.1:8080}"
DIRECT_REST_BASE="${DIRECT_REST_BASE:-}"   # optional
DIRECT_GRPC_HOST="${DIRECT_GRPC_HOST:-}"   # optional

prewarm_pair() {
  local base="$1" host="$2"
  PREWARM=1 REQ_TIMEOUT="$REQ_TIMEOUT" \
  k6 run -u 1 -d 10s --summary-export /tmp/prewarm_rest.json \
    server/tests/performance/rest/k6_rest.js \
    -e BASE="$base" -e MODEL_NAME="$MODEL" -e USE_FILE=1 || true
  PREWARM=1 REQ_TIMEOUT="$REQ_TIMEOUT" MAX_MSG_MB="$MAX_MSG_MB" \
  k6 run -u 1 -d 10s --summary-export /tmp/prewarm_grpc.json \
    server/tests/performance/grpc/k6_grpc.js \
    -e HOST="$host" -e MODEL_NAME="$MODEL" -e USE_FILE=1 || true
}

run_rest() {
  local base="$1" label="$2" noreuse_flag="$3" rep="$4"
  local TS=$(date -u +%Y%m%d_%H%M%S)
  CHECKS_MIN="$CHECKS_MIN" REQ_TIMEOUT="$REQ_TIMEOUT" \
  k6 run $noreuse_flag \
    --summary-export "$OUTR/rest_${label}_v${VUS}_rep${rep}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/rest/k6_rest.js \
    -e BASE="$base" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS="$VUS"
}

run_grpc() {
  local host="$1" label="$2" rep="$3"
  local TS=$(date -u +%Y%m%d_%H%M%S)
  CHECKS_MIN="$CHECKS_MIN" REQ_TIMEOUT="$REQ_TIMEOUT" MAX_MSG_MB="$MAX_MSG_MB" \
  k6 run \
    --summary-export "$OUTG/grpc_${label}_v${VUS}_rep${rep}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/grpc/k6_grpc.js \
    -e HOST="$host" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS="$VUS"
}

# Prewarm (Envoy + optional Direct)
prewarm_pair "$ENVOY_REST_BASE" "$ENVOY_GRPC_HOST"
if [[ -n "$DIRECT_REST_BASE" && -n "$DIRECT_GRPC_HOST" ]]; then
  prewarm_pair "$DIRECT_REST_BASE" "$DIRECT_GRPC_HOST"
fi

for r in "${REPS[@]}"; do
  run_rest "$ENVOY_REST_BASE" "sigmoid_envoy_reuse" "" "$r"
  run_rest "$ENVOY_REST_BASE" "sigmoid_envoy_new"   "--no-connection-reuse" "$r"

  if [[ -n "$DIRECT_REST_BASE" ]]; then
    run_rest "$DIRECT_REST_BASE" "sigmoid_direct_reuse" "" "$r"
    run_rest "$DIRECT_REST_BASE" "sigmoid_direct_new"   "--no-connection-reuse" "$r"
  fi

  run_grpc "$ENVOY_GRPC_HOST" "sigmoid_envoy_reuse" "$r"
  if [[ -n "$DIRECT_GRPC_HOST" ]]; then
    run_grpc "$DIRECT_GRPC_HOST" "sigmoid_direct_reuse" "$r"
  fi
done
echo "E2 complete → $OUT"
