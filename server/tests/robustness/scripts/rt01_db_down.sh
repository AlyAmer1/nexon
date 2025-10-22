#!/usr/bin/env bash
set -euo pipefail

# Config (override via env if your compose service names differ)
MONGO_SVC="${MONGO_SVC:-nexon-mongo}"
DOWN_SECS="${DOWN_SECS:-15}"

cid="$(docker compose ps -q "$MONGO_SVC" 2>/dev/null || true)"
if [[ -z "$cid" ]]; then
  echo "ERROR: Mongo service '$MONGO_SVC' not found via docker compose"; exit 1
fi

echo "[RT01] Stopping Mongo ($MONGO_SVC) for ${DOWN_SECS}s..."
docker stop "$cid" >/dev/null
sleep "$DOWN_SECS"
echo "[RT01] Starting Mongo ($MONGO_SVC)..."
docker start "$cid" >/dev/null
echo "[RT01] Done."
