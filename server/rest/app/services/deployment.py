# server/rest/app/services/deployment.py
from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from bson import ObjectId
from fastapi import APIRouter, HTTPException, Request, UploadFile, File
from pydantic import BaseModel

from shared.database import fs, models_collection

router = APIRouter(prefix="/deployment", tags=["Deployment"])


# --------- Models ---------
class DeployRequest(BaseModel):
    model_name: str
    model_id: str


class DeployResponse(BaseModel):
    message: str
    endpoints: dict  # {rest_envoy, rest_direct, grpc_envoy, grpc_direct, grpc_service}


class UndeployRequest(BaseModel):
    model_name: str
    model_version: int


# --------- Helpers ---------
def _today_str() -> str:
    now = datetime.now()
    return f"{now.day}/{now.month}/{now.year}"  # portable across platforms


def _rest_urls_from_request(base_url: str, model_name: str) -> tuple[str, str]:
    """
    Build absolute REST URLs for Envoy and for the direct FastAPI dev port.
    """
    base = base_url.rstrip("/")  # e.g., http://127.0.0.1:8080
    rest_envoy = f"{base}/inference/infer/{model_name}"

    parsed = urlparse(base)
    scheme = parsed.scheme or "http"
    rest_direct_base = f"{scheme}://127.0.0.1:8000"
    rest_direct = f"{rest_direct_base}/inference/infer/{model_name}"
    return rest_envoy, rest_direct


def _grpc_addrs_from_request(base_url: str) -> tuple[str, str, str]:
    """
    Derive gRPC addresses and FQMN. Envoy address comes from the same host:port as REST.
    """
    parsed = urlparse(base_url)
    grpc_envoy = parsed.netloc or "127.0.0.1:8080"
    grpc_direct = "127.0.0.1:50051"
    grpc_fqmn = "nexon.grpc.inference.v1.InferenceService/Predict"
    return grpc_envoy, grpc_direct, grpc_fqmn


# --------- Routes ---------
@router.post(
    "/deploy-file/",
    response_model=DeployResponse,
    summary="Upload an ONNX file and deploy it immediately (status → Deployed)",
)
async def deploy_file(req: Request, file: UploadFile = File(...)):
    # Parity with original behavior: upload to GridFS, new version, mark Deployed
    if not file.filename.endswith(".onnx"):
        raise HTTPException(status_code=400, detail="Only ONNX files are allowed.")

    # Disallow deploying if any version is already deployed
    existing = [m async for m in models_collection.find({"name": file.filename})]
    for m in existing:
        if m.get("status") == "Deployed":
            raise HTTPException(status_code=400, detail="Another version of this model is already deployed!")

    latest = await models_collection.find_one({"name": file.filename}, sort=[("version", -1)])
    new_version = 1 if latest is None else int(latest["version"]) + 1

    file_id = await fs.upload_from_stream(file.filename, file.file)

    today = _today_str()
    rest_envoy, rest_direct = _rest_urls_from_request(str(req.base_url), file.filename)
    grpc_envoy, grpc_direct, grpc_fqmn = _grpc_addrs_from_request(str(req.base_url))

    meta = {
        "file_id": str(file_id),
        "name": file.filename,
        "upload": today,
        "version": new_version,
        "deploy": today,
        "size": getattr(file, "size", "—"),  # size may not always be available
        "status": "Deployed",
        "endpoint": rest_envoy,  # keep legacy DB field
    }
    await models_collection.insert_one(meta)

    return {
        "message": f"Model {file.filename} uploaded and deployed successfully!",
        "endpoints": {
            "rest_envoy": rest_envoy,
            "rest_direct": rest_direct,
            "grpc_envoy": grpc_envoy,
            "grpc_direct": grpc_direct,
            "grpc_service": grpc_fqmn,
        },
    }


@router.post(
    "/deploy-model/",
    response_model=DeployResponse,
    summary="Deploy an already uploaded model (status → Deployed)",
)
async def deploy_model(request: DeployRequest, base_url_request: Request):
    models = [m async for m in models_collection.find({"name": request.model_name})]
    for m in models:
        if m.get("status") == "Deployed":
            if str(m["_id"]) == request.model_id:
                raise HTTPException(status_code=400, detail="This version is already deployed!")
            raise HTTPException(status_code=400, detail="Another version of this model is already deployed!")

    today = _today_str()
    rest_envoy, rest_direct = _rest_urls_from_request(str(base_url_request.base_url), request.model_name)
    grpc_envoy, grpc_direct, grpc_fqmn = _grpc_addrs_from_request(str(base_url_request.base_url))

    updated = await models_collection.update_one(
        {"_id": ObjectId(request.model_id)},
        {"$set": {"status": "Deployed", "deploy": today, "endpoint": rest_envoy}},
    )
    if updated.modified_count == 0:
        raise HTTPException(status_code=400, detail="Model does not exist")

    return {
        "message": f"Model {request.model_name} deployed successfully!",
        "endpoints": {
            "rest_envoy": rest_envoy,
            "rest_direct": rest_direct,
            "grpc_envoy": grpc_envoy,
            "grpc_direct": grpc_direct,
            "grpc_service": grpc_fqmn,
        },
    }


@router.put(
    "/undeploy/{model_name}",
    summary="Undeploy a model (status → Uploaded)",
)
async def undeploy_model(model_name: str, request: UndeployRequest):
    model = await models_collection.find_one({"name": model_name, "version": int(request.model_version)})
    if not model:
        raise HTTPException(status_code=404, detail="Model not found.")
    if model.get("status") != "Deployed":
        raise HTTPException(status_code=400, detail="Model is not deployed.")

    upd = await models_collection.update_one({"_id": model["_id"]}, {"$set": {"status": "Uploaded"}})
    if upd.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to undeploy model.")
    return {"message": f"Model '{model_name}' (v{request.model_version}) undeployed successfully."}