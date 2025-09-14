# REST inference endpoint using the shared async ModelCache via a shared orchestrator.
from __future__ import annotations

from typing import List
import numpy as np
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

# Project DB handles (Motor GridFS bucket + models collection)
from .database import fs, models_collection

# Shared inference orchestrator (unifies REST & gRPC behavior)
from .shared.orchestrator import (
    InferenceOrchestrator,
    InvalidInputError,
    ModelNotFoundError,
    ModelNotDeployedError,
)

app = FastAPI(title="NEXON REST Inference")

# One orchestrator per process (uses the shared in-process ModelCache)
_orch = InferenceOrchestrator(models_collection=models_collection, gridfs_bucket=fs)


class InferenceRequest(BaseModel):
    # Nested Python lists representing a single input tensor, row-major.
    input: list


@app.post("/infer/{model_name}")
async def infer(request: InferenceRequest, model_name: str):
    """
    Run inference on a deployed ONNX model.

    Contract (parity with gRPC):
      - Resolve by model *name*.
      - Use model input[0]; return only output[0].
      - Cast JSON -> NumPy using the model's declared ONNX dtype.
      - Optional shape check tolerates dynamic dims.
    """
    try:
        # Orchestrator returns a list of NumPy arrays (we return JSON)
        outputs: List[np.ndarray] = await _orch.run(model_name=model_name, input_data=request.input)
        return {"results": [o.tolist() for o in outputs]}
    except ModelNotFoundError as e:
        # Name not present in DB
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotDeployedError as e:
        # Name exists, but no doc with status=Deployed
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidInputError as e:
        # Bad dtype/shape/name mismatch etc.
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        # DB/IO/ORT unexpected errors
        raise HTTPException(status_code=500, detail=f"Server error: {e}")