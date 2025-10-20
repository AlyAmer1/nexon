#!/usr/bin/env bash
set -euo pipefail
in="${1:?input CSV}"; out="${2:?output CSV}"; start="${3:-61}"; end="${4:-180}"
awk -F',' -v s="$start" -v e="$end" 'NR==1{print; next} {i++; if(i>=s && i<=e) print}' "$in" > "$out"
echo "wrote $out (rows $start..$end from $in)"
