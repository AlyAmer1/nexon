#!/usr/bin/env bash
set -euo pipefail
cd "$(git rev-parse --show-toplevel 2>/dev/null || pwd)"

ACC="server/tests/results/functional/ACCEPTANCE_FUNCTIONAL_LOCAL.txt"
GRPC_DIR="server/tests/results/functional/grpc"
REST_DIR="server/tests/results/functional/rest"

latest_rest_json="$(ls -1t "$REST_DIR"/POSTMAN_REST_*.json 2>/dev/null | head -n1 || true)"

{
  echo "# Functional Acceptance — LOCAL"
  date -u
  echo
  echo "## gRPC outcomes ($GRPC_DIR)"

  c02=$(ls -1 "$GRPC_DIR"/ft02_iter*.out  2>/dev/null | wc -l | tr -d ' '); c02=${c02:-0}
  c04=$(ls -1 "$GRPC_DIR"/ft04_iter*.err  2>/dev/null | wc -l | tr -d ' '); c04=${c04:-0}
  c06=$(ls -1 "$GRPC_DIR"/ft06_iter*.err  2>/dev/null | wc -l | tr -d ' '); c06=${c06:-0}
  c08=$(ls -1 "$GRPC_DIR"/ft08_iter*.err  2>/dev/null | wc -l | tr -d ' '); c08=${c08:-0}
  c10=$(ls -1 "$GRPC_DIR"/ft10_iter*.json 2>/dev/null | wc -l | tr -d ' '); c10=${c10:-0}
  c12=$(ls -1 "$GRPC_DIR"/ft12_iter*.json 2>/dev/null | wc -l | tr -d ' '); c12=${c12:-0}
  echo "  iters_detected: FT-02(valid)=${c02}, FT-04(invalid)=${c04}, FT-06(undeployed)=${c06}, FT-08(not_found)=${c08}, FT-10(health)=${c10}, FT-12(readiness)=${c12}"

  pass02="FAIL"; [[ "$c02" -gt 0 && -s "$GRPC_DIR/ft02_iter1.out" ]] && pass02="PASS"
  pass04=$([[ "$c04" -gt 0 ]] && grep -qF 'InvalidArgument'    "$GRPC_DIR/ft04_iter1.err" 2>/dev/null && echo "PASS" || echo "FAIL")
  pass06=$([[ "$c06" -gt 0 ]] && grep -qF 'FailedPrecondition' "$GRPC_DIR/ft06_iter1.err" 2>/dev/null && echo "PASS" || echo "FAIL")
  pass08=$([[ "$c08" -gt 0 ]] && grep -qF 'NotFound'           "$GRPC_DIR/ft08_iter1.err" 2>/dev/null && echo "PASS" || echo "FAIL")
  status10=$(jq -r '.status' "$GRPC_DIR/ft10_iter1.json" 2>/dev/null || echo "(missing)")
  status12=$(jq -r '.status' "$GRPC_DIR/ft12_iter1.json" 2>/dev/null || echo "(missing)")

  echo "FT-02 Predict (valid): $pass02"
  echo "FT-04 INVALID_ARGUMENT: $pass04"
  echo "FT-06 FAILED_PRECONDITION: $pass06"
  echo "FT-08 NOT_FOUND: $pass08"
  echo "FT-10 health status: $status10"
  echo "FT-12 readiness status: $status12"
  echo

  echo "## REST outcomes ($REST_DIR)"
  if [[ -n "$latest_rest_json" && -f "$latest_rest_json" ]]; then
    fname=$(basename "$latest_rest_json")
    echo "REST JSON: $fname"
    pass_rest=$(jq -r '((.run.stats.assertions.failed // 0) == 0) and ((.run.failures | length // 0) == 0)' "$latest_rest_json")
    echo "REST collection: $([[ "$pass_rest" == "true" ]] && echo PASS || echo FAIL)"
    jq -r '
      "  iterations=\(.run.stats.iterations.total // "n/a")",
      "  requests=\(.run.stats.requests.total // "n/a")",
      "  assertions_total=\(.run.stats.assertions.total // "n/a")",
      "  assertions_failed=\(.run.stats.assertions.failed // "n/a")",
      "  failures_len=\((.run.failures | length) // 0)"
    ' "$latest_rest_json"
    echo "  per-case:"
    jq -r '
      (.run.executions // [])
      | group_by(.item.name)
      | map({
          name: (.[0].item.name),
          fails: (map((.assertions // []) | map(select(.error != null)) | length) | add)
        })
      | .[]
      | "    \(.name): \(if .fails == 0 then "PASS" else "FAIL" end)"
    ' "$latest_rest_json"
  else
    echo "REST JSON: (none found)"
    echo "REST collection: MISSING"
  fi
} | tee "$ACC"
echo "Wrote $ACC"
