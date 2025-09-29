# =========================
# NEXON – developer Makefile
# =========================
#
# Usage:
#   make help
#   make dev-bootstrap    # venv + deps + build/install stubs wheel + install app (editable) + checks + .env
#   make docker-up        # build & start the compose stack
#   make clean            # remove venv and local stubs
#   make dist-clean       # also remove Docker images (volumes untouched)

# -------- Config --------
VENV ?= .venv
PY    := $(VENV)/bin/python
PIP   := $(VENV)/bin/pip

PROTO_SCRIPT := server/grpc_service/gen_protos_and_build_stubs.sh
WHEEL_GLOB   := server/stubs/dist/*.whl

.DEFAULT_GOAL := help

# -------- Targets --------
.PHONY: help dev-bootstrap ide-ready init-env venv dev-deps proto wheel install-stubs install-editable import-check check-versions \
        clean dist-clean docker-build docker-up docker-down \
        run-rest run-grpc run-envoy-dev run-mongo-docker run-mongo-native

help:
	@echo "Targets:"
	@echo "  make dev-bootstrap    - Create .env, venv, install deps, generate stubs, install wheel, -e ., checks"
	@echo "    (afterwards: select .venv in your IDE or use make run-rest/run-grpc)"
	@echo "  make ide-ready        - Alias for dev-bootstrap"
	@echo "  make docker-up        - Build and start all services via docker-compose"
	@echo "  make docker-down      - Stop services"
	@echo "  make clean            - Remove local venv and generated stubs"
	@echo "  make dist-clean       - Also remove built Docker images"
	@echo "  make init-env         - Create a default .env at repo root if missing"
	@echo "  make check-versions   - Print grpc/grpcio-tools/protobuf versions"
	@echo "  make import-check     - Sanity import check (inference_pb2*, rest.main, shared.database)"
	@echo "  --- Local run helpers (no venv activation needed) ---"
	@echo "  make run-rest         - Start FastAPI on :8000"
	@echo "  make run-grpc         - Start gRPC server on :50051"
	@echo "  make run-envoy-dev    - Start Envoy (local) on :8080"
	@echo "  make run-mongo-docker - Start MongoDB in Docker on :27017"
	@echo "  make run-mongo-native - Start native mongod (needs MongoDB installed)"

# One-shot for reviewers/supervisors
dev-bootstrap: init-env venv dev-deps proto install-stubs install-editable import-check check-versions
	@printf "\n\033[1;32mNEXON local dev environment is ready.\033[0m\n"
	@echo "Next steps:"
	@echo "  Run directly via Make (macOS/Linux; Windows use WSL2 Ubuntu):"
	@echo "       make run-mongo-native   # MongoDB on localhost:27017"
	@echo "       make run-rest           # FastAPI on :8000"
	@echo "       make run-grpc           # gRPC on :50051"
	@echo "       make run-envoy-dev      # Envoy on :8080 (local)"
	@echo "  Note: Point your IDE to the project venv so imports resolve:"
	@echo "       • PyCharm/IntelliJ: Settings → Project: Python Interpreter → Add → Existing → .venv/bin/python"
	@echo "       • VS Code: Command Palette → Python: Select Interpreter → pick .venv"

# 0) Create .env if missing (prefer copying .env.example; else write defaults)
init-env:
	@if [ ! -f .env ]; then \
	  if [ -f .env.example ]; then \
	    cp .env.example .env && echo "Created .env from .env.example"; \
	  else \
	    printf "NEXON_MONGO_URI=mongodb://mongo:27017\nNEXON_MONGO_DB=onnx_platform\nLOG_HEALTH=1\nENABLE_REFLECTION=1\n" > .env && \
	    echo "Created default .env"; \
	  fi; \
	else \
	  echo "./.env already exists; leaving it untouched."; \
	fi

# 1) Virtualenv
venv:
	python3 -m venv $(VENV)

# 2) Install runtime + dev tooling
dev-deps: venv
	$(PIP) install --upgrade pip
	$(PIP) install -r server/requirements.txt
	@if [ -f requirements-dev.txt ]; then \
	  $(PIP) install -r requirements-dev.txt ; \
	else \
	  echo "WARNING: requirements-dev.txt not found; continuing without dev deps." ; \
	fi

# 3) Generate stubs and build wheel (same flow Docker uses)
proto:
	@chmod +x $(PROTO_SCRIPT)
	bash $(PROTO_SCRIPT)

# 4) (Optional) show wheel
wheel: proto
	@ls -1 $(WHEEL_GLOB)

# 5) Install the generated stubs wheel into the venv
install-stubs: wheel
	$(PIP) install --force-reinstall $(WHEEL_GLOB)

# 6) Install your app code as a package (editable) — requires pyproject.toml at repo root
install-editable:
	$(PIP) install -e .

# 7) Quick import sanity (uses the venv interpreter)
import-check:
	$(PY) -c "import importlib; [importlib.import_module(m) for m in ['inference_pb2','inference_pb2_grpc','rest.main','shared.database']]; print('IMPORTS OK: inference_pb2, inference_pb2_grpc, rest.main, shared.database')"

# 8) Version sanity (helps catch grpc/grpcio-tools mismatches)
check-versions:
	$(PY) -c "from importlib import metadata as m; import grpc, google.protobuf as pb; print('grpcio=', getattr(grpc,'__version__','?')); print('grpcio-tools=', m.version('grpcio-tools')); print('protobuf=', pb.__version__)"

# -------- Local run helpers (foreground; stop with Ctrl-C) --------
run-rest:
	$(PY) -m uvicorn rest.main:app --host 127.0.0.1 --port 8000

run-rest-reload:
	$(PY) -m uvicorn rest.main:app --host 127.0.0.1 --port 8000 --reload

run-grpc:
	$(PY) -m grpc_service.server

run-envoy-dev:
	envoy -c ops/envoy/envoy.dev.yaml --mode serve --log-level info

run-mongo-docker:
	@mkdir -p .mongo-data
	-@docker rm -f local-mongo >/dev/null 2>&1 || true
	docker run --rm --name local-mongo -p 27017:27017 -v $$(pwd)/.mongo-data:/data/db mongo:6

run-mongo-native:
	@mkdir -p $$HOME/data/db
	@command -v mongod >/dev/null 2>&1 || { \
	  echo "ERROR: 'mongod' not found. Install MongoDB or run 'make run-mongo-docker'."; \
	  exit 1; \
	}
	mongod --dbpath $$HOME/data/db

# -------- Docker helpers --------
docker-build:
	docker compose build --no-cache

docker-up:
	docker compose up -d --build

docker-down:
	docker compose down

# -------- Cleanup --------
clean:
	rm -rf $(VENV) server/stubs

dist-clean: clean
	-@docker rmi nexon-rest >/dev/null 2>&1 || true
	-@docker rmi nexon-grpc >/dev/null 2>&1 || true