# REST inference endpoint using the shared async ModelCache via a shared orchestrator.
from __future__ import annotations

from typing import List
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Project DB handles (Motor GridFS bucket + models collection)
from shared.database import fs, models_collection

# Shared inference orchestrator (unifies REST & gRPC behavior)
from shared.orchestrator import (
    InferenceOrchestrator,
    InvalidInputError,
    ModelNotFoundError,
    ModelNotDeployedError,
)

# One orchestrator per process (uses the shared in-process ModelCache)
_orch = InferenceOrchestrator(models_collection=models_collection, gridfs_bucket=fs)

router = APIRouter(prefix="/inference", tags=["Inference"])


class InferenceRequest(BaseModel):
    """Nested Python lists representing a single input tensor (row-major)."""
    input: list = Field(..., example=[[[0.1, 0.2, 0.3]]])


class InferenceResponse(BaseModel):
    results: List[list]


@router.post(
    "/infer/{model_name}",
    response_model=InferenceResponse,
    summary="Run inference on a deployed ONNX model",
    responses={
        400: {"description": "Invalid input (dtype/shape/name mismatch)"},
        404: {"description": "Model not found"},
        500: {"description": "Server error"},
    },
)
async def infer(request: InferenceRequest, model_name: str):
    """
    Contract (parity with gRPC):
    - Resolve by model *name*.
    - Use model input[0]; return only output[0].
    - Cast JSON -> NumPy using the model's declared ONNX dtype.
    - Optional shape check tolerates dynamic dims.
    """
    try:
        outputs: List[np.ndarray] = await _orch.run(
            model_name=model_name, input_data=request.input
        )
        return {"results": [o.tolist() for o in outputs]}
    except ModelNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotDeployedError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {e}")