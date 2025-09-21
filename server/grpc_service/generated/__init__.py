# Make local generated modules importable via the top-level names that grpcio-tools emits.
# This avoids editing generated files or requiring special PYTHONPATH.
from importlib import import_module as _imp
import sys as _sys

# Load the local module (grpc_service/generated/inference_pb2.py) as a package submodule:
_infer_pb2 = _imp('.inference_pb2', __name__)

# Expose it under the top-level name that inference_pb2_grpc.py imports:
_sys.modules.setdefault('inference_pb2', _infer_pb2)

# (No need to alias inference_pb2_grpc; it’s imported via the package path in my code.)
