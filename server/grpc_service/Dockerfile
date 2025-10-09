# ---------- Stage 1: build stubs wheel ----------
FROM python:3.11-slim AS stubs
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir grpcio-tools==1.75.0 tomli-w==1.0.0 mypy-protobuf==3.6.0

# Build context is repo root; copy only what’s needed to bust cache when proto/script change
COPY server/grpc_service/protos/ grpc_service/protos/
COPY server/grpc_service/gen_protos_and_build_stubs.sh grpc_service/gen_protos_and_build_stubs.sh

# Generate *_pb2*.py + *.pyi and build the wheel into /app/server/stubs/dist
RUN bash grpc_service/gen_protos_and_build_stubs.sh

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*

# Install runtime deps
COPY server/requirements.txt /app/server/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/server/requirements.txt

# Install the generated stubs wheel
COPY --from=stubs /app/server/stubs/dist /tmp/stubs/dist
RUN pip install --no-cache-dir /tmp/stubs/dist/*.whl

# Sanity: fail build if stubs aren’t the regenerated ones (must have RequestTensor.data_type)
RUN python - <<'PY'
import inference_pb2 as pb
fields = list(pb.RequestTensor.DESCRIPTOR.fields_by_name)
assert "data_type" in fields, f"Wheel missing 'data_type' in RequestTensor; fields={fields}"
print("stubs OK:", pb.__file__)
PY

# Copy application code last (no generated stubs at top-level here!)
COPY server/ /app/server

# Optional import check (will import the app and still use the wheel stubs)
RUN python - <<'PY'
import grpc_service.server as s  # noqa
print("gRPC server import OK")
PY

# Non-root user
RUN useradd -m appuser
ENV PYTHONUNBUFFERED=1
USER appuser

CMD ["python", "-m", "grpc_service.server"]
