#!/usr/bin/env bash
set -euo pipefail

# DEPRECATED: RU capture runs its own workload; this script is intentionally a no-op
# to avoid producing results/resource_utilization/load/*.summary.json.
# To temporarily re-enable this script, run with: ALLOW_RU_LOAD=1 bash server/tests/resource_utilization/run_ru_load.sh
if [[ -z "${ALLOW_RU_LOAD:-}" ]]; then
  echo "run_ru_load.sh is deprecated. RU capture handles load internally. Nothing to do."
  exit 0
fi

# Resolve repo root
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"

REST_JS="$ROOT/server/tests/performance/rest/k6_rest.js"
GRPC_JS="$ROOT/server/tests/performance/grpc/k6_grpc.js"
LOAD_BASE="$ROOT/server/tests/results/resource_utilization/load"
REST_OUT="$LOAD_BASE/rest"
GRPC_OUT="$LOAD_BASE/grpc"

PREWARM="$ROOT/server/tests/performance/utilities/scripts/prewarm.sh"

# “Same shape as E1”
VUS=1
REPS=3
DUR="${DUR:-30s}"
SLEEP="${SLEEP:-5s}"
MODELS=("sigmoid" "medium_sized_model" "gpt2_dynamic")

CLEAN=0
[[ "${1:-}" == "--clean" ]] && CLEAN=1

mkdir -p "$REST_OUT" "$GRPC_OUT"

if (( CLEAN )); then
  echo "== RU load: cleaning previous RU load JSONs =="
  rm -f "$REST_OUT"/*.summary.json "$GRPC_OUT"/*.summary.json 2>/dev/null || true
fi

# Prewarm (local default 127.0.0.1)
if [ -x "$PREWARM" ]; then
  echo "== RU load: prewarming models =="
  bash "$PREWARM" || true
fi

echo "== RU load: starting (1 VU × 3 reps × 3 models × REST+gRPC) =="
for model in "${MODELS[@]}"; do
  for rep in $(seq 1 $REPS); do
    TS=$(date -u +%Y%m%d_%H%M%S)

    # REST
    OUT="$REST_OUT/rest_${model}_v1_rep${rep}_${TS}.summary.json"
    k6 run --vus "$VUS" --duration "$DUR" \
      --summary-export "$OUT" \
      "$REST_JS" \
      -e BASE="http://127.0.0.1:8080" \
      -e MODEL_NAME="${model}.onnx" \
      -e USE_FILE=1 || true

    # gRPC
    OUT="$GRPC_OUT/grpc_${model}_v1_rep${rep}_${TS}.summary.json"
    k6 run --vus "$VUS" --duration "$DUR" \
      --summary-export "$OUT" \
      "$GRPC_JS" \
      -e HOST="127.0.0.1:8080" \
      -e MODEL_NAME="${model}.onnx" \
      -e USE_FILE=1 || true

    sleep "$SLEEP"
  done
done

echo "== RU load: done =="
echo -n "RU rest JSONs: "; ls -1 "$REST_OUT"/*.summary.json 2>/dev/null | wc -l
echo -n "RU grpc JSONs: "; ls -1 "$GRPC_OUT"/*.summary.json 2>/dev/null | wc -l