#!/usr/bin/env bash
set -euo pipefail

# Default: local Envoy
ENDPOINT="127.0.0.1:8080"
ITERS=1
while [[ $# -gt 0 ]]; do
  case "$1" in
    --endpoint) ENDPOINT="$2"; shift 2;;
    --iters)    ITERS="$2";    shift 2;;
    *) echo "Unknown arg: $1" >&2; exit 1;;
  esac
done

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"                 # server/tests/functional/grpc
TESTS_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"               # server/tests
INPUT_DIR="$SCRIPT_DIR/inputs"                              # server/tests/functional/grpc/inputs
OUT_DIR="$TESTS_ROOT/results/functional/grpc"               # server/tests/results/functional/grpc
mkdir -p "$OUT_DIR"

SVC="nexon.grpc.inference.v1.InferenceService"

require() { [[ -f "$1" ]] || { echo "Missing $1"; exit 1; }; }
require "$INPUT_DIR/sigmoid.json"
require "$INPUT_DIR/medium_1x1.json"

SIGMOID_DIMS="$(jq -c '.dims'  "$INPUT_DIR/sigmoid.json")"
SIGMOID_B64="$(jq -r '.b64'    "$INPUT_DIR/sigmoid.json")"
MEDIUM_DIMS="$(jq -c '.dims'   "$INPUT_DIR/medium_1x1.json")"
MEDIUM_B64="$(jq -r '.b64'     "$INPUT_DIR/medium_1x1.json")"

echo "gRPC endpoint: $ENDPOINT"
echo "Results dir:   $OUT_DIR"
echo "Iterations:    $ITERS"
echo

for i in $(seq 1 "$ITERS"); do
  echo "ITER $i — FT-02 valid"
  grpcurl -plaintext -d "{
    \"model_name\": \"sigmoid.onnx\",
    \"input\": { \"dims\": $SIGMOID_DIMS, \"tensor_content\": \"$SIGMOID_B64\" }
  }" "$ENDPOINT" "$SVC/Predict" \
    > "$OUT_DIR/ft02_iter${i}.out" 2> "$OUT_DIR/ft02_iter${i}.err" || true

  echo "ITER $i — FT-04 invalid (wrong dims)"
  grpcurl -plaintext -d "{
    \"model_name\": \"sigmoid.onnx\",
    \"input\": { \"dims\": [9,9,9], \"tensor_content\": \"$SIGMOID_B64\" }
  }" "$ENDPOINT" "$SVC/Predict" \
    > "$OUT_DIR/ft04_iter${i}.out" 2> "$OUT_DIR/ft04_iter${i}.err" || true

  echo "ITER $i — FT-06 undeployed"
  grpcurl -plaintext -d "{
    \"model_name\": \"medium_sized_model.onnx\",
    \"input\": { \"dims\": $MEDIUM_DIMS, \"tensor_content\": \"$MEDIUM_B64\" }
  }" "$ENDPOINT" "$SVC/Predict" \
    > "$OUT_DIR/ft06_iter${i}.out" 2> "$OUT_DIR/ft06_iter${i}.err" || true

  echo "ITER $i — FT-08 not found"
  grpcurl -plaintext -d "{
    \"model_name\": \"DOES_NOT_EXIST\",
    \"input\": { \"dims\": [1,1], \"tensor_content\": \"$MEDIUM_B64\" }
  }" "$ENDPOINT" "$SVC/Predict" \
    > "$OUT_DIR/ft08_iter${i}.out" 2> "$OUT_DIR/ft08_iter${i}.err" || true

  echo "ITER $i — FT-10 health"
  grpcurl -plaintext -d '{ "service": "nexon.grpc.inference.v1.InferenceService" }' \
    "$ENDPOINT" grpc.health.v1.Health/Check \
    > "$OUT_DIR/ft10_iter${i}.json" 2> "$OUT_DIR/ft10_iter${i}.err" || true

  echo "ITER $i — FT-12 readiness"
  grpcurl -plaintext -d '{ "service": "nexon.grpc.inference.v1.InferenceService" }' \
    "$ENDPOINT" grpc.health.v1.Health/Check \
    > "$OUT_DIR/ft12_iter${i}.json" 2> "$OUT_DIR/ft12_iter${i}.err" || true
done

echo
echo "Quick checks:"
# grpcurl prints CamelCase status names:
grep -qi "InvalidArgument"    "$OUT_DIR/ft04_iter1.err" && echo " - FT-04 InvalidArgument: OK"    || echo " - FT-04 InvalidArgument: MISSING"
grep -qi "FailedPrecondition" "$OUT_DIR/ft06_iter1.err" && echo " - FT-06 FailedPrecondition: OK" || echo " - FT-06 FailedPrecondition: MISSING"
grep -qi "NotFound"           "$OUT_DIR/ft08_iter1.err" && echo " - FT-08 NotFound: OK"           || echo " - FT-08 NotFound: MISSING"
echo -n " - FT-10 health status: " && jq -r '.status' "$OUT_DIR/ft10_iter1.json" 2>/dev/null || echo "(missing)"
echo -n " - FT-12 readiness:     " && jq -r '.status' "$OUT_DIR/ft12_iter1.json" 2>/dev/null || echo "(missing)"
