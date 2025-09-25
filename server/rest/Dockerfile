FROM python:3.11-slim
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/server/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/server/requirements.txt

# Copy whole server (rest, shared, grpc_service)
COPY . /app/server

# Build-time import check
RUN python - <<'PY'
import sys, importlib
print("PYTHON:", sys.executable)
print("sys.path[0]:", sys.path[0])
for m in ["rest.main",
          "shared.database",
          "rest.app.services.inference",
          "rest.app.services.deployment",
          "rest.app.services.upload"]:
    importlib.import_module(m)
print("IMPORTS OK")
PY

RUN useradd -m appuser
ENV PYTHONUNBUFFERED=1
USER appuser

# Run from repo root and point uvicorn at rest.main
WORKDIR /app/server
CMD ["uvicorn", "rest.main:app", "--host", "0.0.0.0", "--port", "8000"]