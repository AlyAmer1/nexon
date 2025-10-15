# 🧪 NEXON: Test Client

Reproducible smoke tests and micro-benchmarks for the NEXON inference services (gRPC and REST) to ensure parity and benchmark performance.

Run all commands from the `./server` directory.

This guide **only** covers quick smoke tests and micro-benchmarks. <br>
For the complete end-to-end and acceptance testing suite, see the instructions in [tests/README.md](../tests/README.md)

---

## 1) Use the included Reference Model

This repository includes a tiny (103-byte) reference model for immediate use: <br>

[`server/tools/presets/sigmoid.onnx`](presets/sigmoid.onnx)


---

## **2) Upload & deploy the model**

### Preferred (one step)

Deploy the reference model in a single request:

```bash
curl -f -X POST http://127.0.0.1:8080/deployment/deploy-file/ \
  -F "file=@tools/presets/sigmoid.onnx"
```

### Optional Fallback (two steps: upload → deploy)

```bash
# 1) Upload (status = Uploaded)
curl -f -X POST http://127.0.0.1:8080/upload/ \
  -F "file=@tools/presets/sigmoid.onnx"

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

Edit this YAML file: [`server/tools/presets/sigmoid_input.yaml`](./presets/sigmoid_input.yaml)


Then run:

```bash
python -m tools.client_test \
  --model-name sigmoid.onnx \
  --input tools/presets/sigmoid_input.yaml
```

The YAML file contains comments and a dtype field. No `--dtype` flag is needed when using `--input`.


---

## CLI options (excerpt)

```text
--model-name <str>             Deployed ONNX model name (e.g., sigmoid.onnx)
--preset sigmoid               Built-in input generator
--input <path>                 YAML file (contains dtype)
--json <path>                  JSON file (use with --dtype)
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
