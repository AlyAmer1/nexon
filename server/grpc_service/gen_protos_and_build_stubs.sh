#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root from this script’s location:
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Paths relative to /app/server in the build container
PROTO_DIR="${ROOT_DIR}/grpc_service/protos"
STUBS_DIR="${ROOT_DIR}/stubs"

# 0) Clean previous artifacts
rm -rf "${STUBS_DIR}"
mkdir -p "${STUBS_DIR}"

# 1) Collect proto files
PROTO_FILES="$(find "${PROTO_DIR}" -type f -name '*.proto' -print | sort || true)"
if [ -z "${PROTO_FILES}" ]; then
  echo "ERROR: No .proto files found in ${PROTO_DIR}" >&2
  exit 1
fi

# 2) Generate Python stubs (+ .pyi type stubs)
python -m grpc_tools.protoc \
  -I "${PROTO_DIR}" \
  --python_out="${STUBS_DIR}" \
  --grpc_python_out="${STUBS_DIR}" \
  --mypy_out="${STUBS_DIR}" \
  ${PROTO_FILES}

# 3) Build a wheel containing the top-level modules (e.g., inference_pb2*.py)
#    We synthesize a minimal pyproject.toml and set the module list dynamically.
PYMODULES="$(find "${STUBS_DIR}" -maxdepth 1 -type f -name '*.py' \
  -exec basename {} .py \; | sort | tr '\n' ',' | sed 's/,$//')"

cat > "${STUBS_DIR}/pyproject.toml" <<'TOML'
[build-system]
requires = ["setuptools>=68", "wheel", "tomli-w"]
build-backend = "setuptools.build_meta"

[project]
name = "nexon-protos"
version = "0.1.0"
requires-python = ">=3.11"
description = "Protobuf/gRPC stubs for NEXON (generated at build time)"

[tool.setuptools]
py-modules = []
include-package-data = true

[tool.setuptools.data-files]
"" = ["*.pyi"]
TOML

python - <<PY
import pathlib, tomllib
from tomli_w import dumps as tomli_w_dumps

pp = pathlib.Path("stubs/pyproject.toml")
data = tomllib.loads(pp.read_text())
mods = [m for m in "${PYMODULES}".split(",") if m]
data.setdefault("tool", {}).setdefault("setuptools", {})["py-modules"] = mods
pp.write_text(tomli_w_dumps(data))
print("py-modules:", mods)
PY

# 4) Build the wheel into stubs/dist
python -m pip wheel "${STUBS_DIR}" -w "${STUBS_DIR}/dist" --no-deps
ls -1 "${STUBS_DIR}/dist"
