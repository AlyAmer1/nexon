FROM python:3.11-slim

WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/server/requirements.txt

COPY . /app/server

RUN useradd -m appuser
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/server
USER appuser

WORKDIR /app/server/grpc_service
# You renamed the entry to server.py — run as module for clean import paths
CMD ["python", "-m", "grpc_service.server"]