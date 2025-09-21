FROM python:3.11-slim

WORKDIR /app/server

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 ca-certificates && \
    rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/server/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/server/requirements.txt

# Copy the whole server context so "shared", "rest", "grpc_service" are all present
COPY . /app/server

# Create non-root user (matches your previous containers)
RUN useradd -m appuser
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app/server
USER appuser

WORKDIR /app/server/rest
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]