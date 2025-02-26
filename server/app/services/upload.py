import onnxruntime as ort
from fastapi import FastAPI, File, UploadFile, HTTPException
from datetime import datetime
from .database import fs, models_collection

import math

app = FastAPI()


def convert_size(size_bytes):
   if size_bytes == 0:
       return "0B"
   size_name = ("Bytes", "KB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB")
   i = int(math.floor(math.log(size_bytes, 1024)))
   p = math.pow(1024, i)
   s = round(size_bytes / p, 2)
   return "%s %s" % (s, size_name[i])


@app.post("/")
async def upload_file(file: UploadFile = File(...)):
    """
    Uploads an ONNX model file
    """

    if not file.filename.endswith(".onnx"):
        raise HTTPException(status_code=400, detail="Only ONNX files are allowed.")
    
    try:
    
     file_id = await fs.upload_from_stream(file.filename, file.file)
     size = convert_size(file.size)
     upload_date = f"{datetime.now().day}/{datetime.now().month}/{datetime.now().year}"

     model_metadata = {
        "file_id": str(file_id),
        "name": file.filename,
        "upload": upload_date,
        "deploy": "",
        "size": size,
        "status": "Uploaded",
     }

     result = await models_collection.insert_one(model_metadata)

     return {
        "message": f"Model {file.filename} uploaded successfully!",
        "model_id": str(result.inserted_id),
        "file_id": str(file_id),
     }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error uploading model: {str(e)}")


