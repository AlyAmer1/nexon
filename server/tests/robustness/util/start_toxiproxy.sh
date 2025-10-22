#!/bin/sh
set -eu

# If 8088 already listening, assume toxiproxy is up and configured.
if nc -z 127.0.0.1 8088 2>/dev/null; then
  echo "[RT04] toxiproxy already listening on 8088"
  exit 0
fi

echo "[RT04] Starting portable toxiproxy on :8088 (HTTP) and :8474 (admin)"

# Pick platform – force arm64 on Apple Silicon; let others default
PLAT=""
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64|Darwin-aarch64) PLAT="--platform linux/arm64/v8" ;;
esac

# Pick Compose network (default: nexon_default)
NET="${COMPOSE_NETWORK:-nexon_default}"
if ! docker network inspect "$NET" >/dev/null 2>&1; then
  # Try to auto-detect a *_default network
  NET="$(docker network ls --format '{{.Name}}' | grep '_default$' | head -n1 || true)"
  [ -n "$NET" ] || NET="nexon_default"
fi

# Clean any previous container
docker rm -f toxiproxy >/dev/null 2>&1 || true

# Run toxiproxy
docker run -d --pull always \
  $PLAT \
  --name toxiproxy \
  --network "$NET" \
  -p 8088:8080 -p 8474:8474 \
  ghcr.io/shopify/toxiproxy:latest

# Wait for port open
for i in 1 2 3 4 5 6 7 8 9 10; do
  if nc -z 127.0.0.1 8088 2>/dev/null; then break; fi
  sleep 1
done

# Create/refresh the proxy envoy :8080 -> envoy:8080 and add 500±50ms latency
docker exec toxiproxy sh -lc '
  set -eu
  toxiproxy-cli delete envoy >/dev/null 2>&1 || true
  toxiproxy-cli create envoy -l 0.0.0.0:8080 -u envoy:8080 >/dev/null
  toxiproxy-cli toxic add envoy -t latency -a latency=500 -a jitter=50 >/dev/null
  toxiproxy-cli list
'

# Final sanity check goes through toxiproxy to envoy /readyz
curl -fsS http://127.0.0.1:8088/readyz >/dev/null && echo "[RT04] toxiproxy ready" || {
  echo "[RT04] WARNING: toxiproxy started but /readyz failed" >&2
  exit 0
}
