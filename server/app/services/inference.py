import onnxruntime as ort
import numpy as np
from fastapi import FastAPI, File, UploadFile, HTTPException
from pydantic import BaseModel
from .database import fs, models_collection
from bson import ObjectId

app = FastAPI()


# Request body for inference
class InferenceRequest(BaseModel):
    input: list

onnx_to_numpy_dtype = {
    "tensor(float)": np.float32,
    "tensor(int64)": np.int64,
    "tensor(double)": np.float64
}



@app.post("/infer/{model_name}")
async def infer(request: InferenceRequest, model_name):
    """
    Runs inference on the uploaded ONNX model with the given inputs.
    """
    #first try catch is for server errors. Second one is for client errors, e.g wrong input
    try :
     models = await models_collection.find({"name": model_name}).to_list(None)
     if not models:
        raise HTTPException(status_code=400, detail="No model with this name has been uploaded")
     file_id = None
     for model in models:
        if model["status"] == "Deployed":
            file_id = model["file_id"]
            break
     if file_id == None:
        raise HTTPException(status_code=400, detail="No model with this name has been deployed")
     grid_out = await fs.open_download_stream(file_id=ObjectId(file_id))
     model_bytes = await grid_out.read()
     session = ort.InferenceSession(model_bytes)
    except Exception as e: 
        raise HTTPException(status_code=500, detail=f"Server error: {str(e)}. This could be due to a corrupted file or a database disconnection. Please try uploading the model again or try again later.")

    try:
        # Convert input data to NumPy array
        
        type = onnx_to_numpy_dtype.get(session.get_inputs()[0].type)
        input_data = np.array(request.input).astype(type)
        input_name = session.get_inputs()[0].name
        output_name = session.get_outputs()[0].name


        # Currently poses some problems because the shape format isn't always the same and mismatching shapes do not necessarily lead to an error

        # Check input shape compatibility
        # expected_shape = session.get_inputs()[0].shape
        # if list(input_data.shape) != expected_shape:
        #     raise HTTPException(
        #         status_code=400,
        #         detail=f"Input shape mismatch. Expected: {expected_shape}, Received: {list(input_data.shape)}",
        #     )

        # Run inference
        results = session.run([output_name], {input_name: input_data})

        json_results = [result.tolist() for result in results]
        return {"results": json_results}

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Inference error: {str(e)}")
