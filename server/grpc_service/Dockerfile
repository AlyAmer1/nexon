# ---------- Stage 1: build stubs wheel ----------
FROM python:3.11-slim AS stubs
WORKDIR /app/server

# Install bash for the script and the proto tooling
RUN apt-get update && apt-get install -y --no-install-recommends \
    bash ca-certificates && rm -rf /var/lib/apt/lists/*

RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir grpcio-tools==1.75.0 tomli-w mypy-protobuf

# Copy protos and the generator script
COPY grpc_service/protos grpc_service/protos
COPY grpc_service/gen_protos_and_build_stubs.sh tools/gen_protos_and_build_stubs.sh

RUN bash tools/gen_protos_and_build_stubs.sh

# ---------- Stage 2: runtime ----------
FROM python:3.11-slim AS runtime
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*

# Runtime deps
COPY requirements.txt /app/server/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/server/requirements.txt

# Install the generated stubs wheel
COPY --from=stubs /app/server/stubs/dist /tmp/stubs/dist
RUN pip install --no-cache-dir /tmp/stubs/dist/*.whl

# Fail build if stubs can’t be imported
RUN python - <<'PY'
import sys
print("PYTHON:", sys.executable)
print("sys.path[:3]:", sys.path[:3])
import inference_pb2, inference_pb2_grpc
print("stubs OK:", inference_pb2.__file__, inference_pb2_grpc.__file__)
PY

# App code last (better layer caching)
COPY . /app/server

RUN useradd -m appuser
ENV PYTHONUNBUFFERED=1
USER appuser

# Run from repo root so top-level packages (e.g., shared) are importable
WORKDIR /app/server
CMD ["python", "-m", "grpc_service.server"]