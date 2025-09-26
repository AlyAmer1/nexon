## 🧪 NEXON Test Clients and Benchmarks

High-quality, reproducible smoke tests and micro-benchmarks for the NEXON inference backends (gRPC and REST). This document is designed for coursework replication and supervisor review.

Run all commands from the `./server` directory. Ensure you have at least one deployed model (e.g., `sigmoid.onnx`). Use the REST docs at `/docs` to upload/deploy.

### gRPC only
```bash
# Connection reuse
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid
# Fresh connection per call
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --fresh-conn
```

### REST only
```bash
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --rest-only
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --rest-only --fresh-conn
```

### Compare gRPC vs REST
```bash
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --compare-rest
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --compare-rest --fresh-conn
```

### Direct backends (measure Envoy overhead)
```bash
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --grpc-addr 127.0.0.1:50051
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --rest-only --rest-base http://127.0.0.1:8000/inference/infer
```

Notes:
-- Add `--iters 1000` (or any N) to average over repeated requests.
-- Swap preset: `--model-name gpt2_dynamic.onnx --preset gpt2`.

### CLI options (excerpt)

```text
--model-name <str>             Deployed ONNX model name (e.g., sigmoid.onnx)
--preset {sigmoid,gpt2}        Built-in input generator
--json <path> --dtype <type>   Use JSON input with explicit dtype
--compare-rest                 Run gRPC then REST and compare outputs
--rest-only                    Only run REST requests
--iters <int>                  Repeat N times to measure averages
--fresh-conn                   Do not reuse connections (worst-case overhead)
--grpc-addr <host:port>        Target gRPC address (default Envoy 127.0.0.1:8080)
--rest-base <url>              REST base URL (default Envoy http://127.0.0.1:8080/inference/infer)
--deadline <sec>               gRPC per-call deadline (default 60s)
```


## 🛠 Troubleshooting

- **"No module named `inference_pb2`" in IDE**
    - Run `make dev-bootstrap` once. It generates stubs and installs the `nexon-protos` wheel locally so editors resolve imports.

- **grpc/grpcio-tools mismatch (e.g., generated code expects >=1.75.0)**
    - Docker: `docker compose build --no-cache && docker compose up -d`.
    - Local: `make dev-bootstrap` (installs matching versions from `requirements-dev.txt`).

- **Changed `.proto` not reflected**
    - Docker: rebuild with `--no-cache`.
    - Local: `make dev-bootstrap` (re-generates stubs and re-installs the wheel).

- **Envoy shows "no healthy upstream"**
    - Local: start REST (`:8000`) and gRPC (`:50051`) before running `envoy.dev.yaml`.
    - Docker: both services must be healthy; check with `docker compose ps` and the service logs.

- **Health probes not visible**
    - Health logging is enabled by default (`LOG_HEALTH=1` in `.env`). To silence, set `LOG_HEALTH=0`.

---