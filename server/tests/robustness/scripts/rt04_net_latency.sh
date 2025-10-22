#!/usr/bin/env bash
set -euo pipefail

# Envoy service name on the Docker network
ENVOY_SVC="${ENVOY_SVC:-nexon-envoy}"
# Listen port on the host (what Client VM / local k6 will target)
LISTEN_PORT="${LISTEN_PORT:-8088}"
# Latency config
LAT_MS="${LAT_MS:-500}"     # moderate 500ms; use 5000 for severe
JITTER_MS="${JITTER_MS:-50}"

NET_NAME="$(docker network ls --format '{{.Name}}' | grep -E 'nexon.*default|default' | head -n1)"

echo "[RT04] Starting toxiproxy on network '$NET_NAME' (if not already)"
docker rm -f toxiproxy >/dev/null 2>&1 || true
docker run -d --pull always --platform linux/arm64/v8 --name toxiproxy --network "$NET_NAME" -p "${LISTEN_PORT}:8080" shopify/toxiproxy >/dev/null

# Create listener "envoy" that forwards to Envoy service:8080
echo "[RT04] Creating proxy envoy :0.0.0.0:8080 -> ${ENVOY_SVC}:8080 (inside toxiproxy)"
docker exec toxiproxy toxiproxy-cli create envoy -l 0.0.0.0:8080 -u "${ENVOY_SVC}:8080" >/dev/null

echo "[RT04] Adding latency toxic: ${LAT_MS}ms ±${JITTER_MS}ms"
docker exec toxiproxy toxiproxy-cli toxic add envoy -t latency -a "latency=${LAT_MS}" -a "jitter=${JITTER_MS}" >/dev/null

echo "[RT04] Active. Point clients at :${LISTEN_PORT}. To remove:"
echo "       docker rm -f toxiproxy"
