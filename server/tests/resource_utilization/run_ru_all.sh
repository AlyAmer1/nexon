#!/usr/bin/env bash
set -euo pipefail

# ---------- config ----------
NAMES="${NAMES:-nexon-envoy nexon-rest nexon-grpc}"   # container list
SAMPLE_SECS="${SAMPLE_SECS:-210}"                     # total sampling wall time
LOAD_SECS="${LOAD_SECS:-150}"                         # steady-state load duration
SLEEP_LEAD="${SLEEP_LEAD:-3}"                         # sampler spin-up lead (sec)

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RU_ROOT="$ROOT/server/tests/results/resource_utilization"
RAW_REST="$RU_ROOT/raw/rest"; RAW_GRPC="$RU_ROOT/raw/grpc"
STEADY_REST="$RU_ROOT/steady/rest"; STEADY_GRPC="$RU_ROOT/steady/grpc"
SUMDIR="$RU_ROOT/summary"
COLLECT="$ROOT/server/tests/resource_utilization/collect_container_stats.sh"

mkdir -p "$RAW_REST" "$RAW_GRPC" "$STEADY_REST" "$STEADY_GRPC" "$SUMDIR"
[ -x "$COLLECT" ] || { echo "Missing $COLLECT"; exit 1; }

# Optional: prewarm
if [ -x "$ROOT/server/tests/performance/utilities/scripts/prewarm.sh" ]; then
  echo ">> Prewarming models..."
  bash "$ROOT/server/tests/performance/utilities/scripts/prewarm.sh" || true
fi

# ---------- payload helpers ----------
rest_payload() {
  case "$1" in
    sigmoid)             echo '{"inputs":[[0.5]]}' ;;
    medium_sized_model)  echo '{"inputs":[[0.5]]}' ;;
    gpt2_dynamic)        echo '{"inputs":[[50256]]}' ;;
    *)                   echo '{"inputs":[[0.5]]}' ;;
  esac
}
grpc_payload() {
  case "$1" in
    sigmoid)             echo '{"model":"sigmoid","inputs":[[0.5]]}' ;;
    medium_sized_model)  echo '{"model":"medium_sized_model","inputs":[[0.5]]}' ;;
    gpt2_dynamic)        echo '{"model":"gpt2_dynamic","inputs":[[50256]]}' ;;
    *)                   echo "{\"model\":\"$1\",\"inputs\":[[0.5]]}" ;;
  esac
}

# ---------- time-series trim to center ~120s ----------
# Computes number of containers from the file, then selects +/- (60 * num_containers) rows around the midpoint.
trim_to_steady() {
  local in="$1" out="$2"
  awk -F, '
    NR==1 { hdr=$0; next }
    { i++; ts[i]=$1; c[i]=$2; cpu[i]=$3+0; mem[i]=$4+0; seen[$2]=1 }
    END{
      n=i; if(n<10){ print hdr > out; for(j=1;j<=n;j++) printf "%s,%s,%.2f,%.2f\n", ts[j], c[j], cpu[j], mem[j] >> out; next }
      m=0; for(k in seen) m++
      win = 60 * m                # half-window in rows ~ 60 seconds worth of rows (per container)
      mid = int(n/2)
      start = mid - win; if(start < 1) start = 1
      stop  = mid + win; if(stop > n) stop = n
      print hdr > out
      for(j=start;j<=stop;j++) printf "%s,%s,%.2f,%.2f\n", ts[j], c[j], cpu[j], mem[j] >> out
    }' out="$out" "$in"
}

# ---------- drivers ----------
run_rest() {
  local model="$1" rep="$2"
  local ts="$(date -u +%Y%m%d_%H%M%S)"
  local raw="$RAW_REST/ru_${model}_rest_rep${rep}_${ts}.csv"
  local steady="$STEADY_REST/ru_${model}_rest_rep${rep}_${ts}.steady.csv"

  bash "$COLLECT" "$SAMPLE_SECS" "$raw" "$NAMES" & sp=$!
  sleep "$SLEEP_LEAD"
  local tmpjs
  tmpjs="$(mktemp).js"
  cat > "$tmpjs" <<JS
import http from 'k6/http';
export let options = { vus: 1, duration: '${LOAD_SECS}s' };
export default function () {
  const url = 'http://127.0.0.1:8080/inference/infer/${model}';
  const payload = JSON.stringify($(rest_payload "$model"));
  http.post(url, payload, { headers: { 'Content-Type': 'application/json' } });
}
JS
  k6 run "$tmpjs" >/dev/null 2>&1 || true
  wait "$sp" || true
  rm -f "$tmpjs"

  trim_to_steady "$raw" "$steady"
}

run_grpc() {
  local model="$1" rep="$2"
  local ts="$(date -u +%Y%m%d_%H%M%S)"
  local raw="$RAW_GRPC/ru_${model}_grpc_rep${rep}_${ts}.csv"
  local steady="$STEADY_GRPC/ru_${model}_grpc_rep${rep}_${ts}.steady.csv"

  bash "$COLLECT" "$SAMPLE_SECS" "$raw" "$NAMES" & sp=$!
  sleep "$SLEEP_LEAD"
  local end=$(( $(date +%s) + LOAD_SECS ))
  local payload='$(grpc_payload "$model")'
  while [ "$(date +%s)" -lt "$end" ]; do
    grpcurl -plaintext -d "$payload" 127.0.0.1:8080 \
      nexon.grpc.inference.v1.InferenceService/Predict >/dev/null 2>&1 || true
  done
  wait "$sp" || true

  trim_to_steady "$raw" "$steady"
}

# ---------- run matrix: 3 reps × (sigmoid, medium, gpt2) × REST->gRPC ----------
models=(sigmoid medium_sized_model gpt2_dynamic)
for rep in 1 2 3; do
  for m in "${models[@]}"; do
    echo "== RU ${m} REST rep${rep} =="
    run_rest "$m" "$rep"
    echo "== RU ${m} gRPC rep${rep} =="
    run_grpc "$m" "$rep"
  done
done

# ---------- summary tables ----------
PEAKS="$SUMDIR/RU_E1_peaks.csv"
MEANS="$SUMDIR/RU_E1_means_by_model_proto.csv"
echo "file,model,proto,rep,container,peak_cpu_pct,peak_mem_pct" > "$PEAKS"

center_peaks() {
  local f="$1" model="$2" proto="$3" rep="$4"
  awk -F, -v file="$(basename "$f")" -v model="$model" -v proto="$proto" -v rep="$rep" '
    NR==1{ next }
    { i++; ts[i]=$1; c[i]=$2; cpu[i]=$3+0; mem[i]=$4+0; seen[$2]=1 }
    END{
      n=i; if(n<10) nextfile
      m=0; for(k in seen) m++
      win = 60 * m
      mid = int(n/2)
      start = mid - win; if(start<1) start=1
      stop  = mid + win; if(stop>n) stop=n
      for(j=start;j<=stop;j++){
        if(cpu[j] > pc[c[j]]) pc[c[j]] = cpu[j]
        if(mem[j] > pm[c[j]]) pm[c[j]] = mem[j]
      }
      for(k in pc) printf "%s,%s,%s,%s,%s,%.2f,%.2f\n", file, model, proto, rep, k, pc[k], pm[k]
    }' "$f" >> "$PEAKS"
}

for f in "$STEADY_REST"/ru_*_rest_rep*.steady.csv; do
  model="$(basename "$f" | sed -E 's/^ru_(.+)_rest_.*/\1/')"
  rep="$(basename "$f" | sed -E 's/.*_rep([0-9]+)_.*/\1/')"
  center_peaks "$f" "$model" "rest" "$rep"
done
for f in "$STEADY_GRPC"/ru_*_grpc_rep*.steady.csv; do
  model="$(basename "$f" | sed -E 's/^ru_(.+)_grpc_.*/\1/')"
  rep="$(basename "$f" | sed -E 's/.*_rep([0-9]+)_.*/\1/')"
  center_peaks "$f" "$model" "grpc" "$rep"
done

echo "model,proto,container,mean_peak_cpu_pct,mean_peak_mem_pct" > "$MEANS"
awk -F, 'NR>1{ key=$2 FS $3 FS $5; n[key]++; cpu[key]+=$6; mem[key]+=$7 }
  END{ for(k in n){ split(k,a,FS);
       printf "%s,%s,%s,%.2f,%.2f\n", a[1],a[2],a[3], cpu[k]/n[k], mem[k]/n[k] } }' \
  "$PEAKS" | sort >> "$MEANS"

echo "Wrote $PEAKS"
echo "Wrote $MEANS"
