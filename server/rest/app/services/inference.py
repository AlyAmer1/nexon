# REST inference endpoint using the shared async ModelCache via a shared orchestrator.
from __future__ import annotations

from typing import List, Optional
import numpy as np
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

# Project DB handles (Motor GridFS bucket + models collection)
from shared.database import fs, models_collection

# Shared inference orchestrator (unifies REST & gRPC)
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
    # Option B′: OPTIONAL dtype for parity with gRPC; if omitted -> derive from model
    dtype: Optional[str] = Field(None, example="float32")


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
    Contract (parity with gRPC, Option B′):
    - Resolve by model *name*.
    - Use model input[0]; return only output[0].
    - If request.dtype is provided, must match model's input dtype; else derive.
    - Cast JSON -> NumPy using the (derived or requested) dtype.
    - Optional shape check tolerates dynamic dims.
    """
    try:
        # Let orchestrator enforce dtype/shape with the same rules as gRPC.
        outputs: List[np.ndarray] = await _orch.run(
            model_name=model_name,
            input_data=request.input,
            request_dtype_str=request.dtype,  # Option B′: optional dtype string
        )
        return {"results": [o.tolist() for o in outputs]}
    except ModelNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except ModelNotDeployedError as e:
        # REST semantics remain 400 for undeployed (as in your plan)
        raise HTTPException(status_code=400, detail=str(e))
    except InvalidInputError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Server error: {e}")
