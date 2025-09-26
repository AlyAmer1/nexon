# NEXON

**NEXON** is an AI model deployment platform for **ONNX** models. It serves feature-parity **inference over REST and gRPC** behind an **Envoy** gateway. Models are stored in **MongoDB GridFS**, and both services share a single **inference orchestrator** with an **in-process LRU/TTL session cache**. All services are containerized and health-checked for reliable bring-up, benchmarking, and grading.
## 🚀 Features
- Upload, deploy, list, and delete ONNX models.
- Inference via REST and gRPC with identical request/response semantics.
- Inference endpoints
  - REST: `POST /inference/infer/{model_name}`
  - gRPC: `InferenceService/Predict`
- Envoy front door (single :8080 for REST + gRPC), admin UI on :9901.
- Health: REST `/healthz` (liveness), `/readyz` (readiness) and gRPC Health service.
- Frontend (REST-only): the React UI invokes REST endpoints and reaches the backend through Envoy on :8080.
- Shared components:
  - [Database (Motor + GridFS)](server/shared/database.py)
  - [Inference Orchestrator](server/shared/orchestrator.py)
  - [In-process Model Cache](server/shared/model_cache.py)
- Reproducible stubs: 
proto stubs generated at build time → packaged as a wheel → installed.
- Modern, modular Python layout suitable for benchmarking and coursework.
- Docker containerization for one-command bring-up, and multi-stage builds for
  gRPC stubs.

---

## 📦 Installation (Docker – recommended)

### **1. Clone the Repository**
```bash
git clone https://github.com/AlyAmer1/nexon.git
cd nexon
```

### **2. Prepare Environment**

Create `.env` at the repo root (from `.env.example`, or let make create one with sane defaults):

```bash
# preferred (creates .env if missing, sets up local venv too)
make init-env
```


Important keys:
- `NEXON_MONGO_URI`: Mongo connection string (Docker default: `mongodb://mongo:27017`).
- `NEXON_MONGO_DB`: database name (default: `onnx_platform`).
- `LOG_HEALTH`: `1` logs health probes; `0` suppresses noisy health access logs.
- `ENABLE_REFLECTION`: `1` to enable gRPC reflection (dev convenience).
- `GRPC_BIND`, `GRPC_MAX_RECV_BYTES`, `GRPC_MAX_SEND_BYTES`: advanced gRPC tuning.

### **3. Build & Start**

```bash
docker compose up -d --build
```

### **4. What's Running**
- Envoy (gateway): `http://localhost:8080`
- REST service (direct): `http://localhost:8000` (HTTP/1.1)
- gRPC service (direct): `localhost:50051` (HTTP/2)
- MongoDB: `localhost:27017`
- Envoy admin: `http://localhost:9901`

Status & logs:
```bash
docker compose ps
docker compose logs -f rest
docker compose logs -f grpc
docker compose logs -f envoy
```

> **Developer note (IDE imports while using Docker)**
> The gRPC stubs (`inference_pb2*`) are generated **inside the images**. Your local IDE may still show unresolved imports because it isn’t using the container’s interpreter.
> - Quick fix for editor-only resolution: run `make dev-bootstrap` once to build/install the stubs wheel into a local `.venv/`, then point your IDE at `.venv/bin/python`.
> - **PyCharm/IntelliJ:** Settings → Project: Python Interpreter → Add → Existing → select `.venv/bin/python`
> - **VS Code:** Command Palette → “Python: Select Interpreter” → choose `.venv`
> (No change is needed to run via Docker—this is just for your editor’s IntelliSense.)

Note: gRPC stubs are generated during the Docker build into `/app/server/stubs/`, packaged as a wheel, and installed into the image. They are not committed to git.

---

## 🧱 Local Development (optional)

This prepares a local virtualenv, generates protobuf/gRPC stubs, installs the stubs wheel, and installs the app in editable mode - so IDEs resolve `inference_pb2*` without warnings.

### 1) One-time dev setup
```bash
# from repo root
make init-env dev-bootstrap
# - creates .env if missing (defaults)
# - creates .venv, installs runtime + dev deps
# - generates protobuf/gRPC stubs, builds & installs the wheel
# - installs your app in editable mode and runs sanity checks
```

### 2) Start services locally (separate terminals)

**MongoDB**
```bash
mkdir -p ~/data/db
make run-mongo-native
```


**REST (FastAPI)**
```bash
make run-rest
```

**gRPC**
```bash
make run-grpc
```

**Envoy (local)**
```bash
# Uses localhost backends (8000/50051)
make run-envoy-dev
```

**Frontend (REST-only)**
```bash
cd frontend
npm install
npm start
# The UI calls REST endpoints (via Envoy on :8080).
```

---

> **🛠️ Developer note (IDE imports)**
> The gRPC stubs (`inference_pb2*`) are generated **inside the images**. Your local IDE may still show unresolved imports because it isn’t using the container’s interpreter.
> - Quick fix for editor-only resolution: After running `make dev-bootstrap` once to build/install the stubs wheel into a local `.venv/`, then point your IDE at `.venv/bin/python`.
> - **PyCharm/IntelliJ:** Settings → Project: Python Interpreter → Add → Existing → select `.venv/bin/python`
> - **VS Code:** Command Palette → “Python: Select Interpreter” → choose `.venv`
    > (No change is needed to run via Docker—this is just for your editor’s IntelliSense.)


---

## 🧩 Architecture at a Glance

```
nexon/
├─ ops/envoy/
│  ├─ envoy.yaml       # Docker routing (service names: rest, grpc)
│  ├─ envoy.dev.yaml   # Local routing (localhost:8000 / :50051)
│  └─ logs/            # access logs (kept in git via .gitkeep)
├─ server/
│  ├─ rest/            # FastAPI app (REST), mounted under Envoy
│  ├─ grpc_service/    # gRPC server, health, protos, stubs build script
│  ├─ shared/
│  │  ├─ database.py          # Mongo (Motor) + GridFS clients
│  │  ├─ orchestrator.py      # shared inference orchestration (REST+gRPC)
│  │  └─ model_cache.py       # ONNXRuntime session cache (LRU/TTL)
│  └─ tools/                  # developer tools, clients
└─ docker-compose.yml         # mongo + rest + grpc + envoy
```

---


## Credits

This work extends the original NEXON project by Hussein Megahed (UI and initial REST workflow).

Additions in this research extension:
- gRPC Inference Service 
- Envoy gateway (unified ingress on :8080)
- Shared components introduced for robustness and performance:
  - Centralized database module (Motor + GridFS)
  - Inference orchestrator (common logic used by REST and gRPC)
  - In-process model cache for ONNX Runtime sessions (LRU/TTL)
- Docker containerization and a wheel-based protobuf/gRPC stubs pipeline for reproducible builds