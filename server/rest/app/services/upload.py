"""Upload endpoints for registering ONNX models and metadata."""

from __future__ import annotations

import math
from datetime import datetime
from fastapi import APIRouter, File, UploadFile, HTTPException
from pydantic import BaseModel

from shared.database import fs, models_collection

router = APIRouter(prefix="/upload", tags=["Upload"])


def convert_size(size_bytes: int) -> str:
    """Convert byte counts into human-readable units."""
    if size_bytes == 0:
        return "0B"
    size_name = ("Bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
    i = int(math.floor(math.log(size_bytes, 1024)))
    p = math.pow(1024, i)
    s = round(size_bytes / p, 2)
    return f"{s} {size_name[i]}"


class UploadResponse(BaseModel):
    """Response payload returned after successfully uploading a model."""
    message: str
    model_id: str
    file_id: str


@router.post(
    "/",
    response_model=UploadResponse,
    summary="Upload an ONNX model (status=Uploaded)",
    responses={400: {"description": "Only .onnx files are allowed"}},
)
async def upload_file(file: UploadFile = File(...)):
    """Persist an ONNX model file to GridFS and record metadata for later deployment."""
    if not file.filename.endswith(".onnx"):
        raise HTTPException(status_code=400, detail="Only ONNX files are allowed.")
    try:
        latest = await models_collection.find_one(
            {"name": file.filename}, sort=[("version", -1)]
        )
        new_version = 1 if latest is None else int(latest["version"]) + 1

        file_id = await fs.upload_from_stream(file.filename, file.file)

        # Preserve semantics; some servers don't expose UploadFile.size → fallback to "unknown"
        size_bytes = getattr(file, "size", None)
        try:
            size = convert_size(int(size_bytes)) if size_bytes is not None else "unknown"
        except Exception:
            size = "unknown"

        # Use portable zero-padded day/month (Windows-compatible)
        upload_date = datetime.now().strftime("%d/%m/%Y")

        meta = {
            "file_id": str(file_id),
            "name": file.filename,
            "upload": upload_date,
            "version": new_version,
            "deploy": "",
            "size": size,
            "status": "Uploaded",
        }
        result = await models_collection.insert_one(meta)

        return {
            "message": f"Model {file.filename} uploaded successfully!",
            "model_id": str(result.inserted_id),
            "file_id": str(file_id),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading model: {e}")