# Stage 1: build gRPC/Protobuf wheel from the current repository
FROM python:3.11-slim AS stubs
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates && rm -rf /var/lib/apt/lists/*

# Tools to generate stubs and build a wheel (aligned with gRPC service versions)
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir grpcio-tools==1.75.0 tomli-w==1.0.0 mypy-protobuf==3.6.0

# Bring in protos + generator script
COPY server/grpc_service/protos/ grpc_service/protos/
COPY server/grpc_service/gen_protos_and_build_stubs.sh grpc_service/gen_protos_and_build_stubs.sh

# Build wheel -> /app/server/stubs/dist/*.whl
RUN bash grpc_service/gen_protos_and_build_stubs.sh


# Stage 2: REST runtime image
FROM python:3.11-slim
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*

# Install runtime deps
COPY server/requirements.txt /app/server/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/server/requirements.txt

# Install the freshly built stubs wheel from the stubs stage
COPY --from=stubs /app/server/stubs/dist /tmp/stubs/dist
RUN pip install --no-cache-dir /tmp/stubs/dist/*.whl

# Copy application code after stubs are installed
COPY server/ /app/server

# Build-time import smoke test (no runtime side effects, no proto-field assertions).
# Purpose: fail the image build early if Python package wiring or import paths are broken.
RUN python - <<'PY'
import importlib
for m in [
    "rest.main",
    "shared.database",
    "rest.app.services.inference",
    "rest.app.services.deployment",
    "rest.app.services.upload",
]:
    importlib.import_module(m)
print("REST imports OK")
PY

# Non-root user
RUN useradd -m appuser
ENV PYTHONUNBUFFERED=1
USER appuser

CMD ["uvicorn", "rest.main:app", "--host", "0.0.0.0", "--port", "8000"]
