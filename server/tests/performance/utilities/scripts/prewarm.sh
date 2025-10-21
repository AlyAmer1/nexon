#!/usr/bin/env bash
set -euo pipefail

# If an IP/host is provided, use it (Client/Server VM case).
# Otherwise default to localhost (developer laptop / local repo case).
VM="${1:-127.0.0.1}"     # e.g., 130.61.225.208 on Server VM when called from Client VM
MODEL="${2:-sigmoid.onnx}"

# Short prewarm defaults (can be overridden via env)
PRE_VUS=${PRE_VUS:-5}
PRE_DUR=${PRE_DUR:-30s}

echo "Prewarm target: http://${VM}:8080"
echo "Health check..."
curl -fsS "http://${VM}:8080/healthz" >/dev/null
curl -fsS "http://${VM}:8080/readyz"  >/dev/null

# Minimal REST sanity only for sigmoid (known float32 shape)
if [[ "$MODEL" == "sigmoid.onnx" ]]; then
  jq -c '{input:.values}' server/tests/performance/common/payloads/sigmoid_values.json \
  | curl -fsS -H 'Content-Type: application/json' -d @- \
      "http://${VM}:8080/inference/infer/${MODEL}" >/dev/null
fi

echo "Warm-up (REST, ${PRE_VUS} VUs, ${PRE_DUR})…"
PREWARM=1 VUS="${PRE_VUS}" DURATION="${PRE_DUR}" k6 run server/tests/performance/rest/k6_rest.js \
  -e BASE="http://${VM}:8080" -e MODEL_NAME="${MODEL}" \
  -e USE_FILE=1 --summary-export=/dev/null >/dev/null

echo "Warm-up (gRPC, ${PRE_VUS} VUs, ${PRE_DUR})…"
if [[ "$MODEL" == "sigmoid.onnx" ]]; then
  PREWARM=1 VUS="${PRE_VUS}" DURATION="${PRE_DUR}" k6 run server/tests/performance/grpc/k6_grpc.js \
    -e HOST="${VM}:8080" -e MODEL_NAME="${MODEL}" \
    -e DIMS='[3,4,5]' -e DTYPE=float32 \
    -e USE_FILE=1 --summary-export=/dev/null >/dev/null
else
  PREWARM=1 VUS="${PRE_VUS}" DURATION="${PRE_DUR}" k6 run server/tests/performance/grpc/k6_grpc.js \
    -e HOST="${VM}:8080" -e MODEL_NAME="${MODEL}" \
    -e USE_FILE=1 --summary-export=/dev/null >/dev/null
fi

echo "Pre-warm complete."
