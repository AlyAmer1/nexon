"""FastAPI entrypoint for the NEXON REST surface with health and inventory routes."""

from __future__ import annotations

import logging
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from bson.errors import InvalidId

# Routers (now APIRouter-based)
from rest.app.services import inference, deployment, upload

# Shared DB handles
from shared.database import fs, models_collection
from shared.database import client as mongo_client

LOG_HEALTH = os.getenv("LOG_HEALTH", "0").lower() in ("1", "true", "yes", "on")

class _HealthAccessFilter(logging.Filter):
    """Suppress health endpoints from access logs unless explicitly enabled."""

    def filter(self, record: logging.LogRecord) -> bool:
        if LOG_HEALTH:
            return True
        msg = record.getMessage()
        return ("/healthz" not in msg) and ("/readyz" not in msg)

logging.getLogger("uvicorn.access").addFilter(_HealthAccessFilter())

openapi_tags = [
    {"name": "Upload", "description": "Upload ONNX models (status -> Uploaded)."},
    {"name": "Deployment", "description": "Deploy or undeploy models (Uploaded <-> Deployed)."},
    {"name": "Inference", "description": "Run inference on deployed models."},
    {"name": "Inventory", "description": "List or delete models."},
]

app = FastAPI(
    title="NEXON REST API",
    version="1.1",
    description="Upload, deploy, and run inference on ONNX models (MongoDB + GridFS).",
    openapi_tags=openapi_tags,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
    swagger_ui_parameters={
        "defaultModelsExpandDepth": -1,  # hide the "Schemas" panel
        "docExpansion": "list",          # collapse endpoints by default (tidier)
    },
)

@app.get("/healthz", include_in_schema=False)
async def healthz():
    """Return service liveness status."""
    return {"status": "ok"}

@app.get("/readyz", include_in_schema=False)
async def readyz():
    """Return readiness status by pinging MongoDB."""
    try:
        await models_collection.database.command("ping")
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"not ready: {e}")

@app.on_event("startup")
async def _on_startup():
    """Emit startup log entry."""
    logging.getLogger("rest").info("REST starting...")

@app.on_event("shutdown")
async def _on_shutdown():
    """Close shared MongoDB client and report shutdown."""
    try:
        mongo_client.close()
    except Exception:
        pass
    logging.getLogger("rest").info("REST shutdown complete.")

# Include routers so everything appears in a single OpenAPI document.
app.include_router(upload.router)
app.include_router(deployment.router)
app.include_router(inference.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

@app.get("/")
async def root():
    """Return a welcome banner for the API root."""
    return {"message": "Welcome to the ONNX Inference API!"}

# Inventory endpoints
@app.get("/deployedModels", tags=["Inventory"])
async def get_deployed_models():
    """List deployed models with serialized identifiers."""
    models = [m async for m in models_collection.find({"status": "Deployed"})]
    for m in models:
        m["_id"] = str(m["_id"])
        m["file_id"] = str(m["file_id"])
    return models

@app.get("/uploadedModels", tags=["Inventory"])
async def get_uploaded_models():
    """List uploaded (not deployed) models with serialized identifiers."""
    models = [m async for m in models_collection.find({"status": "Uploaded"})]
    for m in models:
        m["_id"] = str(m["_id"])
        m["file_id"] = str(m["file_id"])
    return models

@app.get("/allModels", tags=["Inventory"])
async def get_all_models():
    """List all models regardless of status with serialized identifiers."""
    models = [m async for m in models_collection.find({})]
    for m in models:
        m["_id"] = str(m["_id"])
        m["file_id"] = str(m["file_id"])
    return models

@app.delete("/deleteModel/{model_name}/{model_version}", tags=["Inventory"])
async def delete_model(model_name: str, model_version: int):
    """Remove a model and its GridFS payload."""
    model = await models_collection.find_one({"name": model_name, "version": int(model_version)})
    if not model:
        raise HTTPException(status_code=404, detail="Model not found.")
    file_id = model.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="Model does not have a valid file ID.")
    try:
        oid = ObjectId(file_id)
    except InvalidId:
        raise HTTPException(status_code=400, detail="Invalid file_id; expected a valid ObjectId.")
    try:
        await fs.delete(oid)
        delete_result = await models_collection.delete_one({"_id": model["_id"]})
        if delete_result.deleted_count != 1:
            raise HTTPException(status_code=500, detail="Failed to delete model metadata.")
        return {"message": f"Model '{model_name}' (v{model_version}) deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting model: {e}")
