#!/usr/bin/env bash
set -euo pipefail

ROOT="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
ST_R="$ROOT/server/tests/results/resource_utilization/steady/rest"
ST_G="$ROOT/server/tests/results/resource_utilization/steady/grpc"
SUM="$ROOT/server/tests/results/resource_utilization/summary"
mkdir -p "$SUM"

PEAKS_ALL="$SUM/RU_peaks_all.csv"
MEANS_ALL="$SUM/RU_means_all.csv"
MEANS_REST="$SUM/RU_means_rest.csv"
MEANS_GRPC="$SUM/RU_means_grpc.csv"
BUILD_LOG="$SUM/RU_build.log"  # You chose to keep this ignored — fine.

{
  echo "== Resource Utilization summary build =="
  date
  echo "-- Counts (expect 9/9/9/9) --"
  printf "RAW REST   : %8d\n" "$(ls -1 "$ROOT"/server/tests/results/resource_utilization/raw/rest/ru_*_rest_rep*.csv  2>/dev/null | wc -l)"
  printf "RAW gRPC   : %8d\n" "$(ls -1 "$ROOT"/server/tests/results/resource_utilization/raw/grpc/ru_*_grpc_rep*.csv  2>/dev/null | wc -l)"
  printf "STEADY REST: %8d\n" "$(ls -1 "$ST_R"/ru_*_rest_rep*.steady.csv  2>/dev/null | wc -l)"
  printf "STEADY gRPC: %8d\n" "$(ls -1 "$ST_G"/ru_*_grpc_rep*.steady.csv  2>/dev/null | wc -l)"
} | tee "$BUILD_LOG"

# ---------- 1) Build RU_peaks_all.csv (robust filename parse) ----------
tmp_peaks="$(mktemp)"
trap 'rm -f "$tmp_peaks" "$tmp_peaks.sorted" "$MEANS_ALL.body" 2>/dev/null || true' EXIT

for f in "$ST_R"/*.steady.csv "$ST_G"/*.steady.csv; do
  [ -e "$f" ] || continue
  base="$(basename "$f")"

  # ru_<MODEL_WITH_UNDERSCORES>_(rest|grpc)_rep<REP>_<UTC>.steady.csv
  IFS=, read -r model proto rep <<EOF
$(printf '%s' "$base" | sed -E 's#^ru_(.+)_(rest|grpc)_rep([0-9]+)_.+#\1,\2,\3#')
EOF

  # Per-file container peaks
  awk -F, 'NR>1{
      c=$2
      cpu[c]=($3+0>cpu[c]?$3+0:cpu[c])
      mem[c]=($4+0>mem[c]?$4+0:mem[c])
    }
    END{
      for(k in cpu)
        printf "%s,%s,%s,%s,%.2f,%.2f\n",m,p,r,k,cpu[k],mem[k]
    }' m="$model" p="$proto" r="$rep" "$f" >> "$tmp_peaks"
done

# Sort body, then prepend header (don’t sort the header)
sort -t, -k1,1 -k2,2 -k3,3n -k4,4 "$tmp_peaks" > "$tmp_peaks.sorted"
{
  echo "model,proto,rep,container,peak_cpu_pct,peak_mem_pct"
  cat "$tmp_peaks.sorted"
} > "$PEAKS_ALL"

# Guard: only rest|grpc allowed in proto
bad=$(awk -F, 'NR>1 && $2!="rest" && $2!="grpc"{print $0}' "$PEAKS_ALL" | wc -l)
if [ "$bad" -gt 0 ]; then
  echo "ERROR: unexpected proto labels in $PEAKS_ALL" | tee -a "$BUILD_LOG"
  awk -F, 'NR>1 && $2!="rest" && $2!="grpc"{print "  ->",$0}' "$PEAKS_ALL" | tee -a "$BUILD_LOG"
  exit 1
fi

# ---------- 2) Build RU_means_all.csv and splits (headers correct) ----------
awk -F, 'NR>1{
    key=$1 FS $2 FS $4
    n[key]++; cpu[key]+=$5; mem[key]+=$6
  }
  END{
    for(k in n){
      split(k,a,FS)
      printf "%s,%s,%s,%.2f,%.2f\n",a[1],a[2],a[3],cpu[k]/n[k],mem[k]/n[k]
    }
  }' "$PEAKS_ALL" \
| sort -t, -k1,1 -k2,2 -k3,3 > "$MEANS_ALL.body"

echo "model,proto,container,mean_peak_cpu_pct,mean_peak_mem_pct" > "$MEANS_ALL"
cat "$MEANS_ALL.body" >> "$MEANS_ALL"
rm -f "$MEANS_ALL.body"

# Split by proto with header on top
{ head -n1 "$MEANS_ALL"; awk -F, '$2=="rest" && NR>1' "$MEANS_ALL"; } > "$MEANS_REST"
{ head -n1 "$MEANS_ALL"; awk -F, '$2=="grpc" && NR>1' "$MEANS_ALL"; } > "$MEANS_GRPC"

# ---------- 3) Sanity ----------
{
  echo "== Summary files =="
  ls -1 "$MEANS_ALL" "$MEANS_REST" "$MEANS_GRPC" "$PEAKS_ALL"
  echo "== Means sanity =="
  printf "MEANS_ALL rows (expect 18): %8d\n" "$(awk 'NR>1' "$MEANS_ALL" | wc -l)"
  printf "MEANS_REST rows (expect 9): %8d\n"  "$(awk 'NR>1' "$MEANS_REST" | wc -l)"
  printf "MEANS_GRPC rows (expect 9): %8d\n"  "$(awk 'NR>1' "$MEANS_GRPC" | wc -l)"
} | tee -a "$BUILD_LOG"

echo "Done."
