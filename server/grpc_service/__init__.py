# File: server/grpc_service/__init__.py
"""
Minimal package init for grpc_service.

- Keeps the package importable.
- Optionally exposes generated stubs for tools that import them as top-level
  modules (e.g., 'import inference_pb2'), *without* breaking relative imports.
- Does not fail if the stubs are not generated yet.
"""
from __future__ import annotations
import importlib
import sys

# Try to expose generated stubs under both package and top-level names,
# but don't make it a hard dependency at import time.
try:
    _pb = importlib.import_module(__name__ + ".inference_pb2")
    _pb_grpc = importlib.import_module(__name__ + ".inference_pb2_grpc")
    # Allow generated code that does "import inference_pb2" to still work
    sys.modules.setdefault("inference_pb2", _pb)
    sys.modules.setdefault("inference_pb2_grpc", _pb_grpc)
except Exception:
    # Stubs might not be generated yet; ignore quietly.
    pass