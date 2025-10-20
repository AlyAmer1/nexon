#!/usr/bin/env bash
set -euo pipefail

MODEL="sigmoid.onnx"
TREND="min,avg,med,p(90),p(95),p(99),max"
OUT_BASE="server/tests/results/performance/overhead"
OUTR="$OUT_BASE/rest"
OUTG="$OUT_BASE/grpc"
mkdir -p "$OUTR" "$OUTG"

# Timeouts / sizes
export REQ_TIMEOUT="${REQ_TIMEOUT:-120s}"
export MAX_MSG_MB="${MAX_MSG_MB:-256}"

# Endpoints
ENVOY_REST="${ENVOY_REST:-http://127.0.0.1:8080}"
ENVOY_GRPC="${ENVOY_GRPC:-127.0.0.1:8080}"
DIRECT_REST="${DIRECT_REST:-http://127.0.0.1:8000}"

# Auto-detect a direct gRPC port (9000 preferred, else 50051, else blank)
if nc -z 127.0.0.1 9000 2>/dev/null; then
  DIRECT_GRPC="127.0.0.1:9000"
elif nc -z 127.0.0.1 50051 2>/dev/null; then
  DIRECT_GRPC="127.0.0.1:50051"
else
  DIRECT_GRPC=""
fi

TS="$(date -u +%Y%m%d_%H%M%S)"

if [[ "${1:-}" == "--clean" ]]; then
  rm -f "$OUTR"/*.summary.json "$OUTG"/*.summary.json 2>/dev/null || true
fi

# ---------- PREWARM (REST + gRPC; Envoy + Direct) ----------
echo "[E2] Prewarm: REST (Envoy) ..."
k6 run --vus 1 --duration 2s \
  server/tests/performance/rest/k6_rest.js \
  -e PREWARM=1 -e BASE="$ENVOY_REST" -e MODEL_NAME="$MODEL" -e USE_FILE=1 >/dev/null

echo "[E2] Prewarm: REST (Direct) ..."
k6 run --vus 1 --duration 2s \
  server/tests/performance/rest/k6_rest.js \
  -e PREWARM=1 -e BASE="$DIRECT_REST" -e MODEL_NAME="$MODEL" -e USE_FILE=1 >/dev/null

echo "[E2] Prewarm: gRPC (Envoy) ..."
k6 run --vus 1 --duration 2s \
  server/tests/performance/grpc/k6_grpc.js \
  -e PREWARM=1 -e HOST="$ENVOY_GRPC" -e MODEL_NAME="$MODEL" -e USE_FILE=1 \
  -e REQ_TIMEOUT="$REQ_TIMEOUT" -e MAX_MSG_MB="$MAX_MSG_MB" >/dev/null

if [[ -n "$DIRECT_GRPC" ]]; then
  echo "[E2] Prewarm: gRPC (Direct: $DIRECT_GRPC) ..."
  k6 run --vus 1 --duration 2s \
    server/tests/performance/grpc/k6_grpc.js \
    -e PREWARM=1 -e HOST="$DIRECT_GRPC" -e MODEL_NAME="$MODEL" -e USE_FILE=1 \
    -e REQ_TIMEOUT="$REQ_TIMEOUT" -e MAX_MSG_MB="$MAX_MSG_MB" >/dev/null
else
  echo "[E2] Prewarm: gRPC (Direct) skipped — no direct gRPC port up."
fi

# ---------- RUN OVERHEAD (1 VU × 3 reps) ----------
echo "[E2] Running REST arms (Envoy/Direct × reuse/newconn) ..."
for REP in 1 2 3; do
  # Envoy + reuse
  k6 run \
    --summary-export "$OUTR/E3_REST_envoy_reuse_rep${REP}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/rest/k6_rest.js \
    -e BASE="$ENVOY_REST" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1

  # Envoy + new connection per request
  k6 run \
    --no-connection-reuse \
    --summary-export "$OUTR/E3_REST_envoy_newconn_rep${REP}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/rest/k6_rest.js \
    -e BASE="$ENVOY_REST" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1

  # Direct + reuse
  k6 run \
    --summary-export "$OUTR/E3_REST_direct_reuse_rep${REP}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/rest/k6_rest.js \
    -e BASE="$DIRECT_REST" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1

  # Direct + new connection per request
  k6 run \
    --no-connection-reuse \
    --summary-export "$OUTR/E3_REST_direct_newconn_rep${REP}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/rest/k6_rest.js \
    -e BASE="$DIRECT_REST" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1
done

echo "[E2] Running gRPC arms (Envoy/Direct × reuse/newconn) ..."
for REP in 1 2 3; do
  # Envoy + reuse
  k6 run \
    --summary-export "$OUTG/E3_gRPC_envoy_reuse_rep${REP}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/grpc/k6_grpc.js \
    -e HOST="$ENVOY_GRPC" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1 \
    -e REQ_TIMEOUT="$REQ_TIMEOUT" -e MAX_MSG_MB="$MAX_MSG_MB"

  # Envoy + new connection per request (CLOSE_EACH=1 handled in your patched script)
  k6 run \
    --summary-export "$OUTG/E3_gRPC_envoy_newconn_rep${REP}_${TS}.summary.json" \
    --summary-trend-stats "$TREND" \
    server/tests/performance/grpc/k6_grpc.js \
    -e HOST="$ENVOY_GRPC" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1 \
    -e REQ_TIMEOUT="$REQ_TIMEOUT" -e MAX_MSG_MB="$MAX_MSG_MB" -e CLOSE_EACH=1

  if [[ -n "$DIRECT_GRPC" ]]; then
    # Direct + reuse
    k6 run \
      --summary-export "$OUTG/E3_gRPC_direct_reuse_rep${REP}_${TS}.summary.json" \
      --summary-trend-stats "$TREND" \
      server/tests/performance/grpc/k6_grpc.js \
      -e HOST="$DIRECT_GRPC" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1 \
      -e REQ_TIMEOUT="$REQ_TIMEOUT" -e MAX_MSG_MB="$MAX_MSG_MB"

    # Direct + new connection per request
    k6 run \
      --summary-export "$OUTG/E3_gRPC_direct_newconn_rep${REP}_${TS}.summary.json" \
      --summary-trend-stats "$TREND" \
      server/tests/performance/grpc/k6_grpc.js \
      -e HOST="$DIRECT_GRPC" -e MODEL_NAME="$MODEL" -e USE_FILE=1 -e VUS=1 \
      -e REQ_TIMEOUT="$REQ_TIMEOUT" -e MAX_MSG_MB="$MAX_MSG_MB" -e CLOSE_EACH=1
  else
    echo "[note] Skipping gRPC DIRECT arms (no direct port up)."
  fi
done

echo "[E2] Done. Summaries at: $OUT_BASE"
