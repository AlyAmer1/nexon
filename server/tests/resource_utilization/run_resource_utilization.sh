#!/usr/bin/env bash
set -euo pipefail

# ===== Config (override via env if needed) =====
NAMES="${NAMES:-nexon-envoy nexon-rest nexon-grpc}"   # docker container names (space-separated)
SAMPLE_SECS="${SAMPLE_SECS:-210}"                      # total sampling per run (~3m30s k6 stage + margin)
LOAD_SECS="${LOAD_SECS:-150}"                          # active load time (we center-trim to ~120s)
SLEEP_LEAD="${SLEEP_LEAD:-5}"                          # sampler lead-in seconds
REPS="${REPS:-3}"
MODELS=(${MODELS:-sigmoid medium_sized_model gpt2_dynamic})

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
RU_ROOT="$ROOT/server/tests/results/resource_utilization"
RAW_REST="$RU_ROOT/raw/rest"; RAW_GRPC="$RU_ROOT/raw/grpc"
STEADY_REST="$RU_ROOT/steady/rest"; STEADY_GRPC="$RU_ROOT/steady/grpc"
SUMDIR="$RU_ROOT/summary"
COLLECT="$ROOT/server/tests/resource_utilization/collect_container_stats.sh"

mkdir -p "$RAW_REST" "$RAW_GRPC" "$STEADY_REST" "$STEADY_GRPC" "$SUMDIR"
[ -x "$COLLECT" ] || { echo "ERROR: missing $COLLECT"; exit 1; }

# ===== Minimal payload helpers =====
rest_payload() {
  case "$1" in
    sigmoid)             echo '{"inputs":[[0.5]]}' ;;
    medium_sized_model)  echo '{"inputs":[[0.5]]}' ;;
    gpt2_dynamic)        echo '{"inputs":[[50256]]}' ;;
    *)                   echo '{"inputs":[[0.5]]}' ;;
  esac
}
grpc_payload() {
  # NOTE: your proto expects "model_name", not "model"
  case "$1" in
    sigmoid)             echo '{"model_name":"sigmoid","inputs":[[0.5]]}' ;;
    medium_sized_model)  echo '{"model_name":"medium_sized_model","inputs":[[0.5]]}' ;;
    gpt2_dynamic)        echo '{"model_name":"gpt2_dynamic","inputs":[[50256]]}' ;;
    *)                   echo "{\"model_name\":\"$1\",\"inputs\":[[0.5]]}" ;;
  esac
}

# ===== Trim helper: take a centered steady window =====
trim_to_steady() {
  local in="$1" out="$2"
  awk -F, '
    NR==1 { hdr=$0; next }
    { n++; ts[n]=$1; c[n]=$2; cpu[n]=$3+0; mem[n]=$4+0; seen[$2]=1 }
    END{
      if (n < 10) { print hdr > out; for(i=1;i<=n;i++) printf "%s,%s,%.2f,%.2f\n", ts[i], c[i], cpu[i], mem[i] >> out; exit }
      m=0; for(k in seen) m++
      half = 60 * m                 # ~60s per container on each side ≈ 120s total
      mid = int(n/2)
      start = mid - half; if(start<1) start=1
      stop  = mid + half; if(stop>n) stop=n
      print hdr > out
      for(i=start;i<=stop;i++) printf "%s,%s,%.2f,%.2f\n", ts[i], c[i], cpu[i], mem[i] >> out
    }' > "$out" "$in"
}

# ===== REST driver (uses a tiny inline k6 script) =====
run_rest() {
  local model="$1" rep="$2"
  local ts="$(date -u +%Y%m%d_%H%M%S)"
  local raw="$RAW_REST/ru_${model}_rest_rep${rep}_${ts}.csv"
  local steady="$STEADY_REST/ru_${model}_rest_rep${rep}_${ts}.steady.csv"

  bash "$COLLECT" "$SAMPLE_SECS" "$raw" "$NAMES" & sp=$!
  sleep "$SLEEP_LEAD"

  local tmpjs; tmpjs="$(mktemp).js"
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

# ===== gRPC driver (grpcurl loop) =====
run_grpc() {
  local model="$1" rep="$2"
  local ts="$(date -u +%Y%m%d_%H%M%S)"
  local raw="$RAW_GRPC/ru_${model}_grpc_rep${rep}_${ts}.csv"
  local steady="$STEADY_GRPC/ru_${model}_grpc_rep${rep}_${ts}.steady.csv"

  bash "$COLLECT" "$SAMPLE_SECS" "$raw" "$NAMES" & sp=$!
  sleep "$SLEEP_LEAD"

  local end=$(( $(date +%s) + LOAD_SECS ))
  local payload; payload=$(grpc_payload "$model")
  while [ "$(date +%s)" -lt "$end" ]; do
    grpcurl -plaintext -d "$payload" 127.0.0.1:8080 \
      nexon.grpc.inference.v1.InferenceService/Predict >/dev/null 2>&1 || true
  done
  wait "$sp" || true

  trim_to_steady "$raw" "$steady"
}

# ===== Orchestration: REST → gRPC, REPS × MODELS =====
for rep in $(seq 1 "$REPS"); do
  for m in "${MODELS[@]}"; do
    echo "== RU ${m} REST rep${rep} ==";  run_rest "$m" "$rep"
    echo "== RU ${m} gRPC rep${rep} ==";  run_grpc "$m" "$rep"
  done
done

# ===== Summaries (peak per container per run; then mean of peaks) =====
PEAKS="$SUMDIR/RU_peaks.csv"
MEANS="$SUMDIR/RU_means_by_model_proto.csv"
echo "file,model,proto,rep,container,peak_cpu_pct,peak_mem_pct" > "$PEAKS"

emit_peaks() {
  local f="$1" model="$2" proto="$3" rep="$4"
  awk -F, -v file="$(basename "$f")" -v model="$model" -v proto="$proto" -v rep="$rep" '
    NR==1{ next }
    {
      cpu[$2] = (cpu[$2] < $3+0 ? $3+0 : cpu[$2])
      mem[$2] = (mem[$2] < $4+0 ? $4+0 : mem[$2])
    }
    END{ for(k in cpu) printf "%s,%s,%s,%s,%s,%.2f,%.2f\n", file, model, proto, rep, k, cpu[k], mem[k] }
  ' "$f" >> "$PEAKS"
}

for f in "$STEADY_REST"/ru_*_rest_rep*.steady.csv; do
  model="$(basename "$f" | sed -E 's/^ru_(.+)_rest_.*/\1/')"
  rep="$(basename "$f" | sed -E 's/.*_rep([0-9]+)_.*/\1/')"
  emit_peaks "$f" "$model" "rest" "$rep"
done
for f in "$STEADY_GRPC"/ru_*_grpc_rep*.steady.csv; do
  model="$(basename "$f" | sed -E 's/^ru_(.+)_grpc_.*/\1/')"
  rep="$(basename "$f" | sed -E 's/.*_rep([0-9]+)_.*/\1/')"
  emit_peaks "$f" "$model" "grpc" "$rep"
done

echo "model,proto,container,mean_peak_cpu_pct,mean_peak_mem_pct" > "$MEANS"
awk -F, 'NR>1{ key=$2 FS $3 FS $5; n[key]++; cpu[key]+=$6; mem[key]+=$7 }
  END{ for(k in n){ split(k,a,FS);
       printf "%s,%s,%s,%.2f,%.2f\n", a[1],a[2],a[3], cpu[k]/n[k], mem[k]/n[k] } }' \
  "$PEAKS" | sort >> "$MEANS"

echo "== RU done =="
echo "== Wrote: $PEAKS"
echo "== Wrote: $MEANS"
