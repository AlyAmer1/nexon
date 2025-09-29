# 🧪 NEXON Test Clients & Benchmarks

High-quality, reproducible smoke tests and micro-benchmarks for the NEXON inference services (gRPC and REST) to ensure parity and benchmark performance.

Run all commands from the `./server` directory.

---

## **1) Reference model (already in the repo)**

This repository includes a tiny reference model you can use immediately:

```text
server/tools/models/sigmoid.onnx
```

---

## **2) Upload & deploy the model**

### Preferred (one step)

Deploy the reference model in a single request:

```bash
curl -f -X POST http://127.0.0.1:8080/deployment/deploy-file/ \
  -F "file=@tools/models/sigmoid.onnx"
```

### Optional Fallback (two steps: upload → deploy)

```bash
# 1) Upload (status = Uploaded)
curl -f -X POST http://127.0.0.1:8080/upload/ \
  -F "file=@tools/models/sigmoid.onnx"

# Copy the "model_id" value from the upload response, then:

# 2) Deploy (status = Deployed) using model_id from the upload response
curl -f -X POST http://127.0.0.1:8080/deployment/deploy-model/ \
  -H "Content-Type: application/json" \
  -d '{"model_name":"sigmoid.onnx","model_id":"<PASTE_ID_FROM_UPLOAD>"}'
```

---
## **3) Command examples (preset & comparisons)**

### gRPC only (preset)

```bash
# Connection reuse
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid

# Fresh connection per call
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --fresh-conn
```

### REST only (preset)

```bash
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --rest-only
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --rest-only --fresh-conn
```

### Compare gRPC vs REST (preset)

```bash
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --compare-rest
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --compare-rest --fresh-conn
```

### Direct backends (measure Envoy overhead)

```bash
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --grpc-addr 127.0.0.1:50051
python -m tools.client_test --model-name sigmoid.onnx --preset sigmoid --rest-only --rest-base http://127.0.0.1:8000/inference/infer
```

---

## **4) Custom input**

You can supply any input (shape/dtype must match the model’s first input).

Edit this YAML file: [`server/tools/models/sigmoid_input.yaml`](./models/sigmoid_input.yaml)


Then run:

```bash
python -m tools.client_test \
  --model-name sigmoid.onnx \
  --input tools/models/sigmoid_input.yaml
```

The YAML file contains comments and a dtype field. No `--dtype` flag is needed when using `--input`.


---

## CLI options (excerpt)

```text
--model-name <str>             Deployed ONNX model name (e.g., sigmoid.onnx)
--preset sigmoid               Built-in input generator
--input <path>                 YAML or JSON file (includes dtype)
--compare-rest                 Run gRPC then REST and compare outputs
--rest-only                    Only run REST requests
--iters <int>                  Repeat N times to compute averages
--fresh-conn                   Do not reuse connections (worst-case overhead)
--grpc-addr <host:port>        Target gRPC address (default Envoy 127.0.0.1:8080)
--rest-base <url>              REST base URL (default Envoy http://127.0.0.1:8080/inference/infer)
--deadline <sec>               gRPC per-call deadline (default 60s)
```

---

## 🛠 Troubleshooting

### “No module named inference_pb2” in IDE

Run: `make dev-bootstrap` (generates protobuf/gRPC stubs, builds the nexon-protos wheel, installs it into .venv/).
Then point your IDE at the project interpreter:
- macOS/Linux: `.venv/bin/python`
- Windows: `.venv\Scripts\python.exe`

### Changed .proto not reflected

- Docker: rebuild with `--no-cache`.
- Local: `make dev-bootstrap` (re-generates stubs and re-installs the wheel).

### Envoy shows “no healthy upstream”

- Local: start REST (:8000) and gRPC (:50051) before running `envoy.dev.yaml`.
- Docker: ensure both services are healthy; check with `docker compose ps` and service logs.

### Health probes not visible

Health logging is enabled by default (`LOG_HEALTH=1` in `.env`). To silence, set `LOG_HEALTH=0`.
