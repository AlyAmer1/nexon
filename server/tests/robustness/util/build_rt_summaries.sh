#!/bin/sh
set -eu
OUT="server/tests/results/robustness/robustness_summary.csv"
echo "scenario,protocol,k6_file,downtime_seconds,error_rate,checks_pass_rate,p95_duration_ms,total_iterations,pass" > "$OUT"

find server/tests/results/robustness -type f -name '*.summary.json' | sort | while IFS= read -r f; do
  dir=$(dirname "$f")
  proto=$(basename "$dir")
  scen=$(basename "$(dirname "$dir")")
  base=$(basename "$f")

  passes=$(jq -r '.metrics.checks.passes // 0' "$f")
  fails=$(jq -r '.metrics.checks.fails  // 0' "$f")
  denom=$((passes + fails))
  if [ "$denom" -gt 0 ]; then
    checks=$(awk "BEGIN{printf \"%.12f\", $passes/$denom}")
  else
    checks="0"
  fi
  # Uniform strict error rate (thesis-friendly)
  error=$(awk "BEGIN{er=1-$checks; if(er<0) er=0; if(er>1) er=1; printf \"%.12f\", er}")

  # Compact jq filter to avoid multi-line parsing issues
  p95=$(jq -r '(.metrics.http_req_duration["p(95)"] // .metrics.rpc_duration_ms["p(95)"] // .metrics.grpc_req_duration["p(95)"] // 0)' "$f") \
    || { echo "JQ parse error in $f" >&2; exit 1; }

  iters=$(jq -r '(.metrics.iterations.count // .metrics.iterations.value // 0)' "$f")

  case "$scen" in
    RT03_*|RT04_*)
      downtime="N/A"
      ;;
    *)
      latest_log=$(ls -1t "$dir"/READY_MONITOR_*.log 2>/dev/null | head -n1 || true)
      if [ -n "${latest_log:-}" ]; then
        # Portable ERE: -E and + (not \+)
        dt=$(grep -Eo 'downtime[[:space:]][0-9]+s' "$latest_log" | head -n1 | tr -cd '0-9')
        if [ -n "$dt" ]; then
          downtime="$dt"
        else
          down=$(grep -Em1 'DOWN @[[:space:]]*[0-9]+' "$latest_log" | awk '{print $3}')
          up=$(grep -Em1 'UP @[[:space:]]*[0-9]+'   "$latest_log" | awk '{print $3}')
          if [ -n "${down:-}" ] && [ -n "${up:-}" ]; then
            downtime=$((up - down))
          else
            downtime="0"
          fi
        fi
      else
        downtime="0"
      fi
      ;;
  esac

  pass="PASS"
  case "$scen" in
    RT01_*|RT02_*)
      has_down_up=0
      for log in "$dir"/READY_MONITOR_*.log; do
        [ -f "$log" ] || continue
        if grep -q 'DOWN @' "$log" && grep -q 'UP @' "$log"; then
          has_down_up=1
          break
        fi
      done
      if [ "$iters" -le 0 ] || [ "$has_down_up" -eq 0 ]; then pass="FAIL"; fi
      ;;
    RT03_*|RT04_*)
      if [ "$iters" -le 0 ]; then pass="FAIL"; fi
      ;;
  esac

  printf '%s,%s,%s,%s,%s,%.12f,%s,%s,%s\n' \
    "$scen" "$proto" "$base" "$downtime" "$error" "$checks" "$p95" "$iters" "$pass" >> "$OUT"
done

echo "Robustness summary CSV created at: $OUT"
