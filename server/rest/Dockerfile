FROM python:3.11-slim
WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && rm -rf /var/lib/apt/lists/*

# Install runtime deps
COPY server/requirements.txt /app/server/requirements.txt
RUN python -m pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r /app/server/requirements.txt

# Copy only the application subtree
COPY server/ /app/server

# Build-time import check (ensures module wiring is intact)
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
