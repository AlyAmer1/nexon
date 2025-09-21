# File: server/main.py
from __future__ import annotations
import os
import logging
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from bson import ObjectId
from bson.errors import InvalidId

# Sub-apps (your existing modular services)
from app.services.inference import app as inference_app
from app.services.deployment import app as deployment_app
from app.services.upload import app as upload_app

# Shared DB handles (Motor + GridFS)
from shared.database import fs, models_collection
# If you want to close the Motor client on shutdown (recommended):
from shared.database import client as mongo_client


# -----------------------------------------------------------------------------
# Logging: suppress /healthz and /readyz access logs unless LOG_HEALTH=1
# -----------------------------------------------------------------------------
LOG_HEALTH = os.getenv("LOG_HEALTH", "0").lower() in ("1", "true", "yes", "on")

class _HealthAccessFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if LOG_HEALTH:
            return True
        msg = record.getMessage()
        # uvicorn.access format contains the HTTP line; cheap substring check
        return ("/healthz" not in msg) and ("/readyz" not in msg)

# Attach filter to uvicorn access logger
logging.getLogger("uvicorn.access").addFilter(_HealthAccessFilter())

# -----------------------------------------------------------------------------
# App
# -----------------------------------------------------------------------------
app = FastAPI()

# Liveness: fast, independent of external deps (used by Docker healthcheck)
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}

# Readiness: only 200 when Mongo is reachable (optional)
@app.get("/readyz", include_in_schema=False)
async def readyz():
    try:
        await models_collection.database.command("ping")
        return {"status": "ready"}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"not ready: {e}")

# Startup/Shutdown hooks (clean logs + graceful DB close)
@app.on_event("startup")
async def _on_startup():
    logging.getLogger("rest").info("REST starting…")

@app.on_event("shutdown")
async def _on_shutdown():
    try:
        mongo_client.close()
    except Exception:
        pass
    logging.getLogger("rest").info("REST shutdown complete.")

# Mount the inference API to the main app (if modularized)
app.mount("/inference", inference_app)
app.mount("/deployment", deployment_app)
app.mount("/upload", upload_app)

# CORS (relaxed; adjust for prod)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Root endpoint
@app.get("/")
async def root():
    return {"message": "Welcome to the ONNX Inference API!"}

# ----------------------------- Models inventory ------------------------------

@app.get("/deployedModels")
async def get_deployed_models():
    models = [m async for m in models_collection.find({"status": "Deployed"})]
    for m in models:
        m["_id"] = str(m["_id"])
        m["file_id"] = str(m["file_id"])
    return models

@app.get("/uploadedModels")
async def get_uploaded_models():
    models = [m async for m in models_collection.find({"status": "Uploaded"})]
    for m in models:
        m["_id"] = str(m["_id"])
        m["file_id"] = str(m["file_id"])
    return models

@app.get("/allModels")
async def get_all_models():
    models = [m async for m in models_collection.find({})]
    for m in models:
        m["_id"] = str(m["_id"])
        m["file_id"] = str(m["file_id"])
    return models

@app.delete("/deleteModel/{model_name}/{model_version}")
async def delete_model(model_name: str, model_version: int):
    """
    Deletes a specific model version from MongoDB (metadata) and GridFS (binary).
    """
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
        # 1) Delete the ONNX file from GridFS
        await fs.delete(oid)

        # 2) Delete the metadata document
        delete_result = await models_collection.delete_one({"_id": model["_id"]})
        if delete_result.deleted_count != 1:
            raise HTTPException(status_code=500, detail="Failed to delete model metadata.")

        return {"message": f"Model '{model_name}' (v{model_version}) deleted successfully."}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting model: {e}")