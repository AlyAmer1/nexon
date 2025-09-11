# File: server/app/services/inference.py
# REST inference endpoint using the shared async ModelCache (parity with gRPC).

from __future__ import annotations

import numpy as np
import onnxruntime as ort
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Local project services (same DB objects the app already uses)
from .database import fs, models_collection
from .shared.model_cache import ModelCache

app = FastAPI(title="NEXON REST Inference")

# ----- Request model ---------------------------------------------------------

class InferenceRequest(BaseModel):
    # Nested lists representing a single input tensor (row-major).
    input: list

# ----- ONNX -> NumPy dtype mapping (match gRPC) ------------------------------

ONNX_TO_NP = {
    "tensor(float)":   np.float32,
    "tensor(float32)": np.float32,
    "tensor(double)":  np.float64,
    "tensor(float64)": np.float64,
    "tensor(int64)":   np.int64,
    "tensor(int32)":   np.int32,
    "tensor(bool)":    np.bool_,
    "tensor(boolean)": np.bool_,
}

# ----- Create one cache for this process -------------------------------------

# Use the same GridFS bucket as the rest of the REST service.
# ModelCache will log MISS/HIT if MODEL_CACHE_LOG=1 is set in the environment.
_cache = ModelCache(gridfs_db=fs)


def _shape_compatible(expected, actual) -> bool:
    """
    Returns True if 'actual' shape is compatible with 'expected' ONNX input shape.
    Treats dynamic dims (None or -1) as wildcards.
    """
    try:
        exp = list(expected)
        act = list(actual)
    except Exception:
        return False

    if len(exp) != len(act):
        return False

    for e, a in zip(exp, act):
        # ONNX dynamic dims are sometimes None or symbolic; ORT may show -1 as well.
        if e in (None, -1, "None"):
            continue
        if isinstance(e, str):
            # symbolic dim name -> treat as dynamic
            continue
        if int(e) != int(a):
            return False
    return True


@app.post("/infer/{model_name}")
async def infer(request: InferenceRequest, model_name: str):
    """
    Run inference on a deployed ONNX model using a shared in-process session cache.
    Parity with gRPC: resolve by name, use input[0] and return output[0].
    """
    # ---- Resolve deployed model ----
    try:
        docs = await models_collection.find({"name": model_name}).to_list(None)
        file_id = None
        for d in docs or []:
            if d.get("status") == "Deployed":
                file_id = d.get("file_id")
                break
        if file_id is None:
            raise HTTPException(status_code=400, detail=f"No model with name '{model_name}' is deployed.")
    except HTTPException:
        raise
    except Exception as e:
        # DB error or similar
        raise HTTPException(status_code=500, detail=f"Server error while resolving model: {e}")

    # ---- Get/load cached ORT session ----
    try:
        session: ort.InferenceSession = await _cache.get_session(str(file_id))
        if session is None:
            raise HTTPException(status_code=500, detail="Failed to load ONNX model from storage.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error while loading session: {e}")

    # ---- Prepare input ----
    try:
        in_meta = session.get_inputs()[0]
        in_name = in_meta.name
        onnx_dtype = in_meta.type  # e.g. "tensor(float)", "tensor(int64)"
        np_dtype = ONNX_TO_NP.get(onnx_dtype)
        if np_dtype is None:
            raise HTTPException(status_code=400, detail=f"Unsupported ONNX input dtype: {onnx_dtype}")

        # Cast JSON to the model's expected dtype
        arr = np.asarray(request.input, dtype=np_dtype)

        # Optional: shape compatibility check (ignore dynamic dims)
        exp_shape = in_meta.shape  # list with ints/None/-1
        if exp_shape and not _shape_compatible(exp_shape, arr.shape):
            raise HTTPException(
                status_code=400,
                detail=f"Input shape mismatch. Expected ~ {exp_shape}, received {list(arr.shape)}.",
            )

        # ---- Run only output[0] for strict parity ----
        out0_name = session.get_outputs()[0].name
        outputs = session.run([out0_name], {in_name: arr})

        # Convert to pure JSON
        return {"results": [o.tolist() for o in outputs]}

    except HTTPException:
        raise
    except Exception as e:
        # Client errors (bad shape/value) or ORT inference exceptions appear here
        raise HTTPException(status_code=400, detail=f"Inference error: {e}")