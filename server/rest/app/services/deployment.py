from fastapi import FastAPI, File, UploadFile, HTTPException, Request
from pydantic import BaseModel
from datetime import datetime
from shared.database import fs, models_collection
from bson import ObjectId
import math
import psutil

app = FastAPI()



class DeployRequest(BaseModel):
    model_name: str
    model_id: str

class UndeployRequest(BaseModel):
    model_name: str
    model_version: int


class InferenceRequest(BaseModel):
    inputs: list

def convert_size(size_bytes):
   if size_bytes == 0:
       return "0B"
   size_name = ("Bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
   i = int(math.floor(math.log(size_bytes, 1024)))
   p = math.pow(1024, i)
   s = round(size_bytes / p, 2)
   return "%s %s" % (s, size_name[i])


@app.post("/deploy-file/")
async def deploy_file(request: Request, file: UploadFile = File(...)):
    """
    Uploads an ONNX model file and initializes an inference session.
    """
    cpu_before = psutil.cpu_percent()
    mem_before = psutil.virtual_memory().percent
    if not file.filename.endswith(".onnx"):
        raise HTTPException(status_code=400, detail="Only ONNX files are allowed.")
    
    models = await models_collection.find({"name": file.filename}).to_list(None)
    for model in models:
       if (model["status"] == "Deployed"):
        raise HTTPException(status_code=400, detail="Another version of this model is already deployed!")

    try:
        file_id = await fs.upload_from_stream(file.filename, file.file)

        latest_model = await models_collection.find_one(
        {"name": file.filename}, sort=[("version", -1)]
        )

        new_version = 1 if latest_model is None else latest_model["version"] + 1

        size = convert_size(file.size)
        date = f"{datetime.now().day}/{datetime.now().month}/{datetime.now().year}"

        model_metadata = {
        "file_id": str(file_id),
        "name": file.filename,
        "upload": date,
        "version": new_version,
        "deploy": date,
        "size": size,
        "status": "Deployed",
        "endpoint": f"{request.base_url}/inference/infer/{file.filename}"
        }

        result = await models_collection.insert_one(model_metadata)
        cpu_after = psutil.cpu_percent()
        mem_after = psutil.virtual_memory().percent

        print(f"CPU Usage: {cpu_before}% -> {cpu_after}%")
        print(f"Memory Usage: {mem_before}% -> {mem_after}%")

        return {
          "message": f"Model {file.filename} uploaded successfuly!",
          "inference_endpoint": f"http://127.0.0.1:8000/inference/infer/{file.filename}"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deploying model: {str(e)}")


@app.post("/deploy-model/")
async def deploy_model(request: DeployRequest, base_url_request: Request):
    """
    Deploys an already uploaded model
    """
    try:
        models = await models_collection.find({"name": request.model_name}).to_list(None)   
        for model in models:
          if (model["status"] == "Deployed"):
           if model["_id"] == ObjectId(request.model_id):
              raise HTTPException(status_code=400, detail="This version is already deployed!")
           else:
            raise HTTPException(status_code=400, detail="Another version of this model is already deployed!")

        date = f"{datetime.now().day}/{datetime.now().month}/{datetime.now().year}"

        api_endpoint = f"{base_url_request.base_url}/inference/infer/{request.model_name}"

        updated_result = await models_collection.update_one(
            {"_id": ObjectId(request.model_id)},
            {"$set": {"status": "Deployed", "deploy": date, "endpoint": api_endpoint}},
        )
        if updated_result.modified_count > 0:
         return {
          "message": f"Model {request.model_name} deployed successfuly!",
          "inference_endpoint": api_endpoint
         }
        else:
           raise HTTPException(status_code=400, detail="Model does not exist")

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deploying model: {str(e)}")
    

@app.put("/undeploy/{model_name}")
async def undeploy_model(request: UndeployRequest):
    """
    Undeploys a model by updating its status in the database.
    """
    # Find the specific model by name and version
    model = await models_collection.find_one({"name": request.model_name, "version": request.model_version})

    if(model["status"] != "Deployed") :
       raise HTTPException(status_code=400, detail="Model is not deployed")
    

    if not model:
        raise HTTPException(status_code=404, detail="Model not found.")

    # Update model status to 'Pending'
    update_result = await models_collection.update_one(
        {"_id": model["_id"]}, 
        {"$set": {"status": "Uploaded"}}
    )

    if update_result.modified_count == 0:
        raise HTTPException(status_code=500, detail="Failed to undeploy model.")

    return {"message": f"Model '{request.model_name}' (v{request.model_version}) undeployed successfully."}

