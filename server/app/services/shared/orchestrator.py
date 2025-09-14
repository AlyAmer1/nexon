# Async inference orchestrator shared by REST and gRPC.

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, List, Sequence

import numpy as np
import onnxruntime as ort
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorGridFSBucket

from .model_cache import ModelCache


# ---------- Domain errors surfaced to API layers ----------

class ModelNotFoundError(Exception):
    """No document exists for the given model name."""
    pass


class ModelNotDeployedError(Exception):
    """Model exists, but no document is marked status='Deployed'."""
    pass


class InvalidInputError(Exception):
    """Input cannot be bound to model input[0] (dtype/shape/name mismatch)."""
    pass


# ---------- Helpers ----------

# ONNX type → NumPy dtype (little-endian where applicable)
ONNX_TO_NP = {
    "tensor(float)":   np.dtype("<f4"),   # float32
    "tensor(float32)": np.dtype("<f4"),
    "tensor(double)":  np.dtype("<f8"),   # float64
    "tensor(float64)": np.dtype("<f8"),
    "tensor(int64)":   np.dtype("<i8"),
    "tensor(int32)":   np.dtype("<i4"),
    "tensor(bool)":    np.dtype(np.bool_),
    "tensor(boolean)": np.dtype(np.bool_),
}


def _shape_compatible(expected, actual) -> bool:
    """True if 'actual' matches 'expected' shape treating None/-1/symbolic as wildcards."""
    try:
        exp = list(expected)
        act = list(actual)
    except Exception:
        return False
    if len(exp) != len(act):
        return False
    for e, a in zip(exp, act):
        if e in (None, -1, "None"):
            continue
        if isinstance(e, str):  # symbolic name
            continue
        if int(e) != int(a):
            return False
    return True


def _numpy_from_bytes(buf: bytes, dims: Sequence[int], dtype: np.dtype) -> np.ndarray:
    """Rebuild a C-contiguous NumPy array from raw bytes and dims, validating size."""
    dims = [int(d) for d in dims]               # ensure plain ints
    if not dims:
        raise InvalidInputError("input.dims must be provided and non-empty.")

    # validate total byte size using pure-Python types (keeps type-checkers happy)
    elems = 1
    for d in dims:
        elems *= int(d)
    elem_size = 1 if dtype == np.dtype(np.bool_) else int(dtype.itemsize)
    expected = elems * elem_size
    if len(buf) != expected:
        raise InvalidInputError(
            f"tensor_content size {len(buf)} != prod(dims) {elems} * elem_size {elem_size}"
        )

    mv = memoryview(buf)
    if dtype == np.dtype(np.bool_):
        arr = np.frombuffer(mv, dtype=np.uint8).astype(np.bool_, copy=False)
    else:
        arr = np.frombuffer(mv, dtype=dtype)

    return np.ascontiguousarray(arr).reshape(tuple(dims))


# ---------- Orchestrator ----------

@dataclass
class InferenceOrchestrator:
    """
    Coordinates: DB lookup → GridFS → ModelCache → ONNX Runtime.

    One instance per process is fine; it holds an in-process cache only.
    """
    models_collection: Any
    gridfs_bucket: AsyncIOMotorGridFSBucket
    _cache: ModelCache | None = None

    @property
    def cache(self) -> ModelCache:
        # Lazy init to keep construction light.
        if self._cache is None:
            self._cache = ModelCache(gridfs_db=self.gridfs_bucket)
        return self._cache

    async def _resolve_deployed_file_id(self, model_name: str) -> ObjectId:
        docs = await self.models_collection.find({"name": model_name}).to_list(None)
        if not docs:
            raise ModelNotFoundError(f"Model '{model_name}' does not exist.")
        for d in docs:
            if d.get("status") == "Deployed":
                return ObjectId(str(d["file_id"]))
        raise ModelNotDeployedError(f"Model '{model_name}' has no deployed version.")

    async def _load_session(self, file_id: ObjectId) -> ort.InferenceSession:
        sess = await self.cache.get_session(file_id)
        if sess is None:
            raise RuntimeError("Failed to load ONNX session from cache.")
        return sess

    # -------- REST path: JSON lists → NumPy --------
    async def run(self, *, model_name: str, input_data: Any) -> List[np.ndarray]:
        """
        Resolve deployed model by name, load session from cache, and execute output[0]
        using input bound to input[0]. Returns a list with one NumPy array.
        """
        file_id = await self._resolve_deployed_file_id(model_name)
        session = await self._load_session(file_id)

        in_meta = session.get_inputs()[0]
        in_name = in_meta.name
        onnx_dt = in_meta.type or ""
        np_dtype = ONNX_TO_NP.get(onnx_dt)
        if np_dtype is None:
            raise InvalidInputError(f"Unsupported ONNX input dtype: {onnx_dt}")

        try:
            arr = np.asarray(input_data, dtype=np_dtype)
        except Exception as e:
            raise InvalidInputError(f"Failed to cast input to {onnx_dt}: {e}")

        exp_shape = in_meta.shape
        if exp_shape and not _shape_compatible(exp_shape, arr.shape):
            raise InvalidInputError(
                f"Input shape mismatch. Expected ~ {exp_shape}, received {list(arr.shape)}."
            )

        out0_name = session.get_outputs()[0].name
        outputs = session.run([out0_name], {in_name: arr})
        return [np.asarray(outputs[0])]

    # -------- gRPC path: raw bytes + dims → NumPy --------
    async def run_from_bytes(
            self,
            *,
            model_name: str,
            dims: Sequence[int],
            raw_bytes: bytes,
            provided_name: str = "",
    ) -> List[np.ndarray]:
        """
        Same as `run`, but accepts a pre-serialized tensor:
        - dims: shape of the input
        - raw_bytes: row-major tensor bytes
        - provided_name: optional; if given, must match model input[0].name
        """
        file_id = await self._resolve_deployed_file_id(model_name)
        session = await self._load_session(file_id)

        in_meta = session.get_inputs()[0]
        in_name = in_meta.name
        onnx_dt = in_meta.type or ""
        np_dtype = ONNX_TO_NP.get(onnx_dt)
        if np_dtype is None:
            raise InvalidInputError(f"Unsupported ONNX input dtype: {onnx_dt}")

        if provided_name and provided_name != in_name:
            raise InvalidInputError(f"input.name '{provided_name}' does not match model input[0] '{in_name}'.")

        dims = [int(d) for d in dims]
        arr = _numpy_from_bytes(raw_bytes, dims, np_dtype)

        exp_shape = in_meta.shape
        if exp_shape and not _shape_compatible(exp_shape, arr.shape):
            raise InvalidInputError(
                f"Input shape mismatch. Expected ~ {exp_shape}, received {list(arr.shape)}."
            )

        out0_name = session.get_outputs()[0].name
        outputs = session.run([out0_name], {in_name: arr})
        return [np.asarray(outputs[0])]