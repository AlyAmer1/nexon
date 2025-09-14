from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from app.services.inference import app as inference_app
from app.services.deployment import app as deployment_app
from app.services.upload import app as upload_app
from app.services.database import fs, models_collection
from bson import ObjectId


# Create the main FastAPI app
app = FastAPI()

# Health endpoint for Envoy/monitoring
@app.get("/healthz", include_in_schema=False)
async def healthz():
    return {"status": "ok"}

# Mount the inference API to the main app (if modularized)
app.mount("/inference", inference_app)
app.mount("/deployment", deployment_app)
app.mount("/upload", upload_app)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],  # Allow all HTTP methods (GET, POST, etc.)
    allow_headers=["*"],  # Allow all headers
)

# Root endpoint (optional)
@app.get("/")
async def root():
    return {"message": "Welcome to the ONNX Inference API!"}


@app.get("/deployedModels")
async def getUploadedModels():
    models = await models_collection.find({"status": "Deployed"}).to_list()
    for model in models:
        model["_id"] = str(model["_id"])
        model["file_id"] = str(model["file_id"])

    return models

@app.get("/uploadedModels")
async def getUploadedModels():
    models = await models_collection.find({"status": "Uploaded"}).to_list()
    for model in models:
        model["_id"] = str(model["_id"])
        model["file_id"] = str(model["file_id"])

    return models

@app.get("/allModels")
async def getAllModels():
    models = await models_collection.find().to_list()
    for model in models:
        model["_id"] = str(model["_id"])
        model["file_id"] = str(model["file_id"])

    return models


@app.delete("/deleteModel/{model_name}/{model_version}")
async def delete_model(model_name: str, model_version: int):
    """
    Deletes a model by name from the database and GridFS storage.
    """
    model = await models_collection.find_one({"name": model_name, "version": model_version})
    if not model:
        raise HTTPException(status_code=404, detail="Model not found.")

    # Ensure the file_id exists
    file_id = model.get("file_id")
    if not file_id:
        raise HTTPException(status_code=400, detail="Model does not have a valid file ID.")

    try:
        # Delete the file from GridFS
        await fs.delete(ObjectId(file_id))  # Ensure we pass an ObjectId

        # Delete model metadata
        delete_result = await models_collection.delete_one({"_id": model["_id"]})

        if delete_result.deleted_count == 1:
            return {"message": f"Model '{model_name}' deleted successfully"}
        else:
            raise HTTPException(status_code=500, detail="Failed to delete model.")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting model: {str(e)}")