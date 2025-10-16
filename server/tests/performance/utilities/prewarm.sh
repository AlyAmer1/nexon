#!/usr/bin/env bash
set -euo pipefail

VM="${1:?server VM IP required}"     # e.g., 10.0.1.67
MODEL="${2:-sigmoid.onnx}"

echo "Pre-flight: http://${VM}:8080/healthz and /readyz"
curl -fsS "http://${VM}:8080/healthz" >/dev/null
curl -fsS "http://${VM}:8080/readyz"  >/dev/null

# Minimal REST sanity only for sigmoid (known float32 shape)
if [[ "$MODEL" == "sigmoid.onnx" ]]; then
  jq -c '{input:.values}' server/tests/performance/common/payloads/sigmoid_values.json \
  | curl -fsS -H 'Content-Type: application/json' -d @- \
      "http://${VM}:8080/inference/infer/${MODEL}" >/dev/null
fi

echo "Warm-up (REST, 10 VUs, 60s)…"
k6 run server/tests/performance/rest/k6_rest.js \
  -e BASE="http://${VM}:8080" -e MODEL_NAME="${MODEL}" \
  -e VUS=10 -e USE_FILE=1 --summary-export=/dev/null >/dev/null

echo "Warm-up (gRPC, 10 VUs, 60s)…"
if [[ "$MODEL" == "sigmoid.onnx" ]]; then
  k6 run server/tests/performance/grpc/k6_grpc.js \
    -e HOST="${VM}:8080" -e MODEL_NAME="${MODEL}" \
    -e DIMS='[3,4,5]' -e DTYPE=float32 \
    -e VUS=10 -e USE_FILE=1 --summary-export=/dev/null >/dev/null
else
  # GPT-2 and medium infer dims/dtype internally unless overridden
  k6 run server/tests/performance/grpc/k6_grpc.js \
    -e HOST="${VM}:8080" -e MODEL_NAME="${MODEL}" \
    -e VUS=10 -e USE_FILE=1 --summary-export=/dev/null >/dev/null
fi
echo "Pre-warm complete."
