# File: server/grpc_service/grpc_server.py
# Description: The main gRPC server for the NEXON Inference Service.

import grpc
from concurrent import futures
import time
import os
import sys
import asyncio
import numpy as np

# --- Add project root to path to allow absolute imports ---
# This ensures that we can reliably import modules from the 'app' directory.
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
sys.path.append(PROJECT_ROOT)

# --- Imports from our project ---
# Import the generated gRPC classes
import grpc_service.inference_pb2 as inference_pb2
import grpc_service.inference_pb2_grpc as inference_pb2_grpc
# Import the shared model cache
from app.services.shared.model_cache import ModelCache
# Import the database connection objects (motor client and GridFS)
from app.services.database import models_collection, fs as gridfs_storage

# --- gRPC Service Implementation ---

# This class implements the "InferenceService" defined in our .proto file.
# It corresponds to the "Inference Orchestrator" and "gRPC API Handler"
# components in the Level 3 architecture diagram.
class InferenceService(inference_pb2_grpc.InferenceServiceServicer):
    """
    Implements the gRPC InferenceService for handling model predictions.
    This service is responsible for orchestrating the inference process, including
    fetching model metadata, utilizing a cache for performance, and running the
    ONNX model.
    """

    def __init__(self):
        """
        Initializes the service, creating an instance of the ModelCache.
        """
        try:
            # Instantiate the shared model cache, passing the GridFS object to it.
            self.model_cache = ModelCache(gridfs_db=gridfs_storage)
            print("ModelCache initialized successfully.")
        except Exception as e:
            print(f"FATAL: Failed to initialize ModelCache: {e}")
            sys.exit(1)


    async def Predict(self, request: inference_pb2.PredictRequest, context) -> inference_pb2.PredictReply:
        """
        Handles the incoming "Predict" RPC call. This is the core of our service.
        It is an `async` method to work with the asynchronous database driver (motor).
        """
        print(f"Received Predict request for model: {request.model_name} v{request.model_version}")

        # --- 1. Fetch Model Metadata from MongoDB ---
        model_metadata = await models_collection.find_one({
            "name": request.model_name,
            "version": request.model_version,
            "status": "Deployed"
        })

        if not model_metadata:
            print(f"Error: Deployed model '{request.model_name}' v{request.model_version} not found.")
            context.set_code(grpc.StatusCode.NOT_FOUND)
            context.set_details(f"Deployed model '{request.model_name}' version {request.model_version} not found.")
            return inference_pb2.PredictReply()

        file_id = str(model_metadata.get("file_id"))

        # --- 2. Get Inference Session from Cache ---
        # This corresponds to the "Lookup inference session" step in the detailed gRPC flow diagram.
        session = self.model_cache.get_session(file_id)

        if session is None:
            print(f"Error: Failed to load ONNX session for file_id {file_id}.")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Failed to load ONNX model file from storage. It may be corrupted.")
            return inference_pb2.PredictReply()

        # --- 3. Prepare Inputs, Run Inference, Prepare Outputs ---
        try:
            # This corresponds to the "ONNX Runtime Executor" component from the architecture diagram.

            # a. Convert the incoming Protobuf Tensors to a dictionary of NumPy arrays.
            input_feed = {}
            for i, proto_tensor in enumerate(request.inputs):
                np_array = self._proto_to_numpy(proto_tensor)
                input_name = proto_tensor.name or session.get_inputs()[i].name
                input_feed[input_name] = np_array

            # b. Run the inference using `session.run()`.
            output_names = [output.name for output in session.get_outputs()]
            result_np_list = session.run(output_names, input_feed)

            # c. Convert the resulting NumPy arrays back into a PredictReply message.
            response = inference_pb2.PredictReply()
            for i, output_np in enumerate(result_np_list):
                proto_tensor = self._numpy_to_proto(output_np, name=output_names[i])
                response.outputs.append(proto_tensor)

            print(f"Successfully ran inference for model '{request.model_name}' v{request.model_version}.")
            return response

        except Exception as e:
            print(f"Error during inference execution: {e}")
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details(f"Error during model execution. Check tensor shapes and data types: {e}")
            return inference_pb2.PredictReply()

    # --- Private Helper Methods for Data Conversion ---

    def _proto_to_numpy(self, proto_tensor: inference_pb2.Tensor) -> np.ndarray:
        """Converts a Protobuf Tensor message to a NumPy array."""
        dims = list(proto_tensor.dims)

        # Mapping from Protobuf enum to NumPy data types.
        dtype_map = {
            inference_pb2.DT_FLOAT32: np.float32,
            inference_pb2.DT_FLOAT64: np.float64,
            inference_pb2.DT_INT32: np.int32,
            inference_pb2.DT_INT64: np.int64,
            inference_pb2.DT_BOOL: np.bool_,
        }

        np_dtype = dtype_map.get(proto_tensor.data_type)
        if np_dtype is None:
            raise ValueError(f"Unsupported Protobuf DataType: {proto_tensor.data_type}")

        # Reconstruct the NumPy array from the raw bytes and shape information.
        return np.frombuffer(proto_tensor.tensor_content, dtype=np_dtype).reshape(dims)

    def _numpy_to_proto(self, np_array: np.ndarray, name: str = "") -> inference_pb2.Tensor:
        """Converts a NumPy array to a Protobuf Tensor message."""
        proto_tensor = inference_pb2.Tensor()
        proto_tensor.name = name
        proto_tensor.dims.extend(np_array.shape)

        # Mapping from NumPy data types to Protobuf enum.
        dtype_map = {
            np.float32: inference_pb2.DT_FLOAT32,
            np.float64: inference_pb2.DT_FLOAT64,
            np.int32: inference_pb2.DT_INT32,
            np.int64: inference_pb2.DT_INT64,
            np.bool_: inference_pb2.DT_BOOL,
        }

        proto_dtype = dtype_map.get(np_array.dtype.type)
        if proto_dtype is None:
            raise ValueError(f"Unsupported NumPy dtype: {np_array.dtype}")

        proto_tensor.data_type = proto_dtype
        proto_tensor.tensor_content = np_array.tobytes()

        return proto_tensor


# --- Server Startup Logic ---

async def serve():
    """Initializes and starts the asynchronous gRPC server."""
    server = grpc.aio.server(futures.ThreadPoolExecutor(max_workers=10))

    inference_pb2_grpc.add_InferenceServiceServicer_to_server(InferenceService(), server)

    listen_addr = '[::]:50051'
    server.add_insecure_port(listen_addr)

    print(f"gRPC server starting on {listen_addr}...")
    await server.start()

    try:
        await server.wait_for_termination()
    except KeyboardInterrupt:
        print("Stopping gRPC server.")
        await server.stop(0)

if __name__ == '__main__':
    # Using asyncio.run() is the standard way to run an async application.
    asyncio.run(serve())