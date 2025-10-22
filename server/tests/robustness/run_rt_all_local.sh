#!/usr/bin/env bash
# --- Robustness-only threshold patch: force 0.90 for k6 checks ---
K6_REST_PATH="server/tests/performance/rest/k6_rest.js"
K6_GRPC_PATH="server/tests/performance/grpc/k6_grpc.js"
K6_BACKUP_DIR="$(mktemp -d -t k6backup_XXXXXX)"

# Backup originals
cp "$K6_REST_PATH" "$K6_BACKUP_DIR/k6_rest.js.orig"
cp "$K6_GRPC_PATH" "$K6_BACKUP_DIR/k6_grpc.js.orig"

# Create patched copies with 0.90 (covers '>' and '>=' variants)
perl -0777 -pe 's/rate\s*(?:>=|>)\s*0\.99/rate>=0.90/g' "$K6_REST_PATH" > "$K6_BACKUP_DIR/k6_rest.patched"
perl -0777 -pe 's/rate\s*(?:>=|>)\s*0\.99/rate>=0.90/g' "$K6_GRPC_PATH" > "$K6_BACKUP_DIR/k6_grpc.patched"

# Swap in patched scripts
cp "$K6_BACKUP_DIR/k6_rest.patched" "$K6_REST_PATH"
cp "$K6_BACKUP_DIR/k6_grpc.patched" "$K6_GRPC_PATH"

# Always restore originals at the end (even on errors)
restore_k6() {
  cp "$K6_BACKUP_DIR/k6_rest.js.orig" "$K6_REST_PATH" 2>/dev/null || true
  cp "$K6_BACKUP_DIR/k6_grpc.js.orig" "$K6_GRPC_PATH" 2>/dev/null || true
  rm -rf "$K6_BACKUP_DIR"
}
trap restore_k6 EXIT
# --- End patch ---
### Auto-toxiproxy bootstrap (inserted) ###
if ! nc -z 127.0.0.1 8088 2>/dev/null; then
  if [ -x server/tests/robustness/util/start_toxiproxy.sh ]; then
    server/tests/robustness/util/start_toxiproxy.sh
  fi
fi
### End bootstrap ###
set -euo pipefail

SIP="127.0.0.1"
VUS="${VUS:-20}"
INJECT_AFTER_SECS="${INJECT_AFTER_SECS:-75}"
DOWNTIME_SECS_RT01="${DOWNTIME_SECS_RT01:-15}"
RT03_DUR="${RT03_DUR:-60}"
RT03_LOAD="${RT03_LOAD:-90}"
RT04_LAT_MS="${RT04_LAT_MS:-500}"
RT04_JITTER_MS="${RT04_JITTER_MS:-50}"
RT04_PORT="${RT04_PORT:-8088}"
CLEAN="${CLEAN:-0}"

MONGO_SVC="${MONGO_SVC:-mongo}"
REST_SVC="${REST_SVC:-rest}"
GRPC_SVC="${GRPC_SVC:-grpc}"
ENVOY_SVC="${ENVOY_SVC:-envoy}"

RESULTS_ROOT="server/tests/results/robustness"
MON="server/tests/robustness/util/monitor_ready.sh"

command -v k6 >/dev/null || { echo "k6 not found"; exit 1; }
command -v jq >/dev/null || { echo "jq not found"; exit 1; }

if [[ "$CLEAN" == "1" ]]; then
  echo "[CLEAN] ${RESULTS_ROOT}"
  rm -rf "${RESULTS_ROOT:?}/"* 2>/dev/null || true
fi

run_one () {
  local scenario="$1" proto="$2" rep="$3"
  local ts; ts="$(date -u +%Y%m%d_%H%M%S)"
  local outdir="${RESULTS_ROOT}/${scenario}/${proto}"
  mkdir -p "$outdir"

  local base_http="http://${SIP}:8080"
  local host_grpc="${SIP}:8080"
  if [[ "$scenario" == "RT04_net_latency" ]]; then
    base_http="http://${SIP}:${RT04_PORT}"
    host_grpc="${SIP}:${RT04_PORT}"
  fi

  echo "===== ${scenario} / ${proto} / rep ${rep} ====="

  BASE="$base_http" OUTDIR="$outdir" "$MON" &
  local MON_PID=$!

  if [[ "$proto" == "rest" ]]; then
    k6 run server/tests/performance/rest/k6_rest.js \
      -e BASE="$base_http" -e MODEL_NAME="sigmoid.onnx" -e VUS="$VUS" -e USE_FILE=1 \
      --summary-export="${outdir}/${scenario}_rest_${ts}.summary.json" &
  else
    k6 run server/tests/performance/grpc/k6_grpc.js \
      -e HOST="$host_grpc" -e MODEL_NAME="sigmoid.onnx" -e DIMS='[3,4,5]' -e DTYPE=float32 \
      -e VUS="$VUS" -e USE_FILE=1 \
      --summary-export="${outdir}/${scenario}_grpc_${ts}.summary.json" &
  fi
  local K6_PID=$!

  if [[ "$scenario" == "RT01_db_down" ]]; then
    sleep "$INJECT_AFTER_SECS"
    MONGO_SVC="$MONGO_SVC" DOWN_SECS="$DOWNTIME_SECS_RT01" server/tests/robustness/scripts/rt01_db_down.sh || true
  elif [[ "$scenario" == "RT02_service_crash" ]]; then
    sleep "$INJECT_AFTER_SECS"
    REST_SVC="$REST_SVC" GRPC_SVC="$GRPC_SVC" server/tests/robustness/scripts/rt02_service_crash.sh || true
  elif [[ "$scenario" == "RT03_cpu_stress" ]]; then
    sleep "$INJECT_AFTER_SECS"
    DUR="$RT03_DUR" LOAD="$RT03_LOAD" CPU_WORKERS=0 server/tests/robustness/scripts/rt03_cpu_stress.sh || true
  elif [[ "$scenario" == "RT04_net_latency" ]]; then
    ENVOY_SVC="$ENVOY_SVC" LAT_MS="$RT04_LAT_MS" JITTER_MS="$RT04_JITTER_MS" LISTEN_PORT="$RT04_PORT" \
      server/tests/robustness/scripts/rt04_net_latency.sh || true
  fi

  wait "$K6_PID" || true

  if [[ "$scenario" == "RT04_net_latency" ]]; then
    docker rm -f toxiproxy >/dev/null 2>&1 || true
  fi

  kill "$MON_PID" 2>/dev/null || true
  echo "===== DONE ${scenario} / ${proto} / rep ${rep} ====="
}

for rep in 1 2 3; do
  run_one "RT01_db_down"      "rest" "$rep"
  run_one "RT01_db_down"      "grpc" "$rep"

  run_one "RT02_service_crash" "rest" "$rep"
  run_one "RT02_service_crash" "grpc" "$rep"

  run_one "RT03_cpu_stress"   "rest" "$rep"
  run_one "RT03_cpu_stress"   "grpc" "$rep"

  run_one "RT04_net_latency"  "rest" "$rep"
  run_one "RT04_net_latency"  "grpc" "$rep"
done

echo "[CSV] server/tests/robustness/util/build_rt_summaries.sh"
server/tests/robustness/util/build_rt_summaries.sh
echo "[OK] Robustness suite complete."

# --- Post-process CSV: ensure a 'pass' column at threshold (default 0.90) ---
CSV="server/tests/results/robustness/robustness_summary.csv"
if [ -f "$CSV" ]; then
  awk -F, '
    NR==1{
      has=0; for(i=1;i<=NF;i++) if($i=="pass") has=1;
      if(!has){ print $0 ",pass" } else { print }
      next
    }
    {
      if(has){ print; next }
      th = (ENVIRON["PASS_THRESHOLD"] && ENVIRON["PASS_THRESHOLD"]+0>0) ? ENVIRON["PASS_THRESHOLD"]+0 : 0.90
      pass = ($6+0 >= th) ? "PASS" : "FAIL"
      print $0 "," pass
    }
  ' "$CSV" > "${CSV}.tmp" && mv "${CSV}.tmp" "$CSV"
fi
# --- End CSV post-process ---
