# ---------- Stage 1: build stubs wheel ----------
FROM python:3.11-slim AS stubs
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir grpcio-tools==1.75.0 tomli-w==1.0.0 mypy-protobuf==3.6.0

# Build context is repo root -> prefix paths with "server/"
COPY server/grpc_service/protos grpc_service/protos
COPY server/grpc_service/gen_protos_and_build_stubs.sh tools/gen_protos_and_build_stubs.sh

# Generate *_pb2*.py + *.pyi and build the wheel into /app/server/stubs/dist
RUN bash tools/gen_protos_and_build_stubs.sh

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*

# Install runtime deps
COPY server/requirements.txt /app/server/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/server/requirements.txt

# Install the generated stubs wheel (top-level imports as gRPC expects)
COPY --from=stubs /app/server/stubs/dist /tmp/stubs/dist
RUN pip install --no-cache-dir /tmp/stubs/dist/*.whl

# Sanity: fail build if stubs aren’t importable
RUN python - <<'PY'
import sys
print("PYTHON:", sys.executable)
print("sys.path[:3]:", sys.path[:3])
import inference_pb2, inference_pb2_grpc
print("stubs OK:", inference_pb2.__file__, inference_pb2_grpc.__file__)
PY

# Copy only the application subtree
COPY server/ /app/server

# Optional import check for the server module
RUN python - <<'PY'
import grpc_service.server as s
print("gRPC server import OK")
PY

# Non-root user
RUN useradd -m appuser
ENV PYTHONUNBUFFERED=1
USER appuser

WORKDIR /app/server
CMD ["python", "-m", "grpc_service.server"]