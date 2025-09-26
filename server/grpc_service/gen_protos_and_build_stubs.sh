#!/usr/bin/env bash
set -euo pipefail

# Resolve repo root as: <this file>/..
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${ROOT_DIR}"

# Paths relative to repo root (/app/server in Docker)
PROTO_DIR="${ROOT_DIR}/grpc_service/protos"
STUBS_DIR="${ROOT_DIR}/stubs"

rm -rf "${STUBS_DIR}"
mkdir -p "${STUBS_DIR}"

# Collect .proto files (portable; no bash 4+ features)
PROTO_FILES="$(find "${PROTO_DIR}" -type f -name '*.proto' -print | sort || true)"
if [ -z "${PROTO_FILES}" ]; then
  echo "ERROR: No .proto files found in ${PROTO_DIR}" >&2
  exit 1
fi

# 1) Generate *_pb2*.py and type stubs (*.pyi) into a flat directory
#    (word-splitting on ${PROTO_FILES} is intentional; paths shouldn't contain spaces)
python -m grpc_tools.protoc \
  -I "${PROTO_DIR}" \
  --python_out="${STUBS_DIR}" \
  --grpc_python_out="${STUBS_DIR}" \
  --mypy_out="${STUBS_DIR}" \
  ${PROTO_FILES}

# 2) Build pyproject.toml with py-modules listing all generated Python modules
PYMODULES="$(find "${STUBS_DIR}" -maxdepth 1 -type f -name '*.py' \
  -exec basename {} .py \; | sort | tr '\n' ',' | sed 's/,$//')"

cat > "${STUBS_DIR}/pyproject.toml" <<'TOML'
[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[project]
name = "nexon-protos"
version = "0.1.0"
requires-python = ">=3.11"
description = "Protobuf/gRPC stubs for NEXON (generated at build time)"

[tool.setuptools]
# These are top-level modules like "inference_pb2"
py-modules = []
# Also ship the *.pyi type stubs so IDEs can resolve symbols
include-package-data = true

# Install *.pyi files at site-packages root (next to the py-modules)
[tool.setuptools.data-files]
"" = ["*.pyi"]
TOML

# Inject the discovered modules
python - <<PY
import pathlib, tomllib, tomli_w
pp = pathlib.Path("stubs/pyproject.toml")
data = tomllib.loads(pp.read_text())
mods = [m for m in "${PYMODULES}".split(",") if m]
data.setdefault("tool", {}).setdefault("setuptools", {})["py-modules"] = mods
pp.write_text(tomli_w.dumps(data))
print("py-modules:", mods)
PY

# 3) Build the wheel into stubs/dist
python -m pip wheel "${STUBS_DIR}" -w "${STUBS_DIR}/dist" --no-deps
ls -1 "${STUBS_DIR}/dist"