#!/usr/bin/env bash
set -euo pipefail
REST_SVC="${REST_SVC:-rest}"
GRPC_SVC="${GRPC_SVC:-grpc}"
PAUSE_AFTER_KILL="${PAUSE_AFTER_KILL:-10}"

for svc in "$REST_SVC" "$GRPC_SVC"; do
  cid="$(docker compose ps -q "$svc" 2>/dev/null || true)"
  if [[ -z "$cid" ]]; then echo "ERROR: service '$svc' not found"; exit 1; fi
done

echo "[RT02] Killing REST service ($REST_SVC)..."
docker kill "$(docker compose ps -q "$REST_SVC")" >/dev/null 2>&1 || true
sleep "$PAUSE_AFTER_KILL"

echo "[RT02] Killing gRPC service ($GRPC_SVC)..."
docker kill "$(docker compose ps -q "$GRPC_SVC")" >/dev/null 2>&1 || true
sleep "$PAUSE_AFTER_KILL"

echo "[RT02] Ensuring services are up (local fallback)..."
docker compose up -d "$REST_SVC" "$GRPC_SVC"
echo "[RT02] Done."
