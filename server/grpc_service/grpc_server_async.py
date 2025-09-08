# File: server/grpc_service/grpc_server_async.py
# Async gRPC Inference server (strict parity with FastAPI /infer/{model_name})

from __future__ import annotations
import os
import asyncio
import logging
import numpy as np
import grpc

# Load environment from server/.env
from dotenv import load_dotenv
# This will find server/.env when run from repo root or from server/
load_dotenv()

# Generated stubs (when run via: python -m grpc_service.grpc_server_async)
import inference_pb2 as pb
import inference_pb2_grpc as pb_grpc

# Project services
from app.services.shared.model_cache import ModelCache

# Per-process Mongo/Motor client & GridFS bucket (avoid cross-loop globals)
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

log = logging.getLogger("grpc_server")
logging.basicConfig(level=os.environ.get("LOGLEVEL", "INFO"))
logging.getLogger("model_cache").setLevel(logging.INFO)

# ---- ONNX -> NumPy type mapping (little-endian where applicable)
ONNX_TO_NP = {
    "tensor(float)":   np.dtype("<f4"),
    "tensor(float32)": np.dtype("<f4"),
    "tensor(double)":  np.dtype("<f8"),
    "tensor(float64)": np.dtype("<f8"),
    "tensor(int64)":   np.dtype("<i8"),
    "tensor(int32)":   np.dtype("<i4"),
    "tensor(bool)":    np.dtype(np.bool_),
    "tensor(boolean)": np.dtype(np.bool_),
}

# NumPy dtype -> proto enum (for responses)
NP_TO_PROTO = {
    np.dtype(np.float32): pb.DT_FLOAT32,
    np.dtype(np.float64): pb.DT_FLOAT64,
    np.dtype(np.int32):   pb.DT_INT32,
    np.dtype(np.int64):   pb.DT_INT64,
    np.dtype(np.bool_):   pb.DT_BOOL,
}

async def _debug_log_deployed_names(models_collection):
    """Log deployed model names (sanity check that we see the same DB as FastAPI)."""
    try:
        names = []
        async for m in models_collection.find({"status": "Deployed"}):
            n = m.get("name")
            if n:
                names.append(n)
        log.info("Deployed models visible to gRPC: %s", names)
    except Exception as e:
        log.warning("Could not list deployed models: %s", e)

class InferenceService(pb_grpc.InferenceServiceServicer):
    """Implements Predict with strict parity: uses input[0], returns output[0]."""

    def __init__(self, models_collection, gridfs_bucket: AsyncIOMotorGridFSBucket):
        self._models = models_collection
        self.model_cache = ModelCache(gridfs_db=gridfs_bucket)
        log.info("ModelCache initialized.")

    async def Predict(self, request: pb.PredictRequest, context: grpc.aio.ServicerContext) -> pb.PredictReply:
        model_name = request.model_name.strip()
        if not model_name:
            context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
            context.set_details("model_name must be non-empty.")
            return pb.PredictReply()

        # 1) Find a deployed model by name (mirror FastAPI behavior)
        try:
            models = await self._models.find({"name": model_name}).to_list(None)
            file_id = None
            for m in models or []:
                if m.get("status") == "Deployed":
                    file_id = str(m.get("file_id"))
                    break
            if file_id is None:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)  # FastAPI returns 400 in this case
                context.set_details(f"No model with name '{model_name}' is deployed.")
                return pb.PredictReply()
        except Exception as e:
            log.exception("Error resolving model metadata")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Server error while resolving model: {e}")
            return pb.PredictReply()

        # 2) Get/load ONNX Runtime session from cache
        try:
            session = await self.model_cache.get_session(file_id)
            if session is None:
                context.set_code(grpc.StatusCode.INTERNAL)
                context.set_details("Failed to load ONNX model from storage.")
                return pb.PredictReply()
        except Exception as e:
            log.exception("Error loading session")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Server error while loading session: {e}")
            return pb.PredictReply()

        # 3) Derive dtype from model, validate & decode request tensor
        try:
            in_meta = session.get_inputs()[0]
            in_dtype = ONNX_TO_NP.get(in_meta.type)
            if in_dtype is None:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"Unsupported ONNX input dtype: {in_meta.type}")
                return pb.PredictReply()

            t = request.input
            dims = list(t.dims)
            if not dims:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details("Input dims must be provided (non-empty).")
                return pb.PredictReply()

            buf = t.tensor_content
            elem_size = 1 if in_dtype == np.dtype(np.bool_) else int(in_dtype.itemsize)
            expected_len = int(np.prod(dims)) * elem_size
            if len(buf) != expected_len:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(
                    f"tensor_content size {len(buf)} != prod(dims) {int(np.prod(dims))} * elem_size {elem_size}"
                )
                return pb.PredictReply()

            # Reconstruct NumPy in row-major
            if in_dtype == np.dtype(np.bool_):
                arr = np.frombuffer(buf, dtype=np.uint8).astype(np.bool_, copy=False).reshape(dims)
            else:
                arr = np.frombuffer(buf, dtype=in_dtype).reshape(dims)

            # Bind strictly to input[0] (parity). If name provided and mismatches -> 400
            in_name = in_meta.name
            if t.name and t.name != in_name:
                context.set_code(grpc.StatusCode.INVALID_ARGUMENT)
                context.set_details(f"input.name '{t.name}' does not match model input[0] '{in_name}'.")
                return pb.PredictReply()

            # 4) Run only output[0] (parity with FastAPI)
            out0 = session.get_outputs()[0].name
            out_arr = session.run([out0], {in_name: arr})[0]

            # 5) Build reply with dtype for client decode
            return pb.PredictReply(outputs=[self._to_response_tensor(out_arr, name=out0)])

        except grpc.RpcError:
            raise  # already set code/details
        except Exception as e:
            log.exception("Unexpected inference error")
            context.set_code(grpc.StatusCode.INTERNAL)
            context.set_details(f"Inference error: {e}")
            return pb.PredictReply()

    def _to_response_tensor(self, arr: np.ndarray, name: str = "") -> pb.ResponseTensor:
        # Ensure contiguous row-major and little-endian bytes
        if arr.dtype != np.bool_:
            le = arr.dtype.newbyteorder("<")
            arr = arr.astype(le, copy=False)
        arr = np.ascontiguousarray(arr)

        proto_dtype = (
                NP_TO_PROTO.get(arr.dtype)
                or NP_TO_PROTO.get(arr.dtype.newbyteorder("="))
                or NP_TO_PROTO.get(arr.dtype.newbyteorder("<"))
        )
        if proto_dtype is None:
            raise ValueError(f"Unsupported output dtype: {arr.dtype}")

        t = pb.ResponseTensor()
        t.name = name
        t.dims.extend(list(arr.shape))
        t.tensor_content = arr.tobytes(order="C")
        t.data_type = proto_dtype
        return t


async def serve():
    """Start the async gRPC server and shut down cleanly on exit."""
    # --- Per-process MongoDB client/bucket (avoids cross-loop sharing)
    mongo_uri = os.environ.get("NEXON_MONGO_URI", "mongodb://localhost:27017")
    mongo_db  = os.environ.get("NEXON_MONGO_DB",  "onnx_platform")  # default matches FastAPI

    client = AsyncIOMotorClient(mongo_uri)
    db = client[mongo_db]
    models_collection = db["models"]
    gridfs_bucket = AsyncIOMotorGridFSBucket(db)

    # --- gRPC server options
    max_recv = int(os.environ.get("GRPC_MAX_RECV_BYTES", 32 * 1024 * 1024))  # 32 MiB
    max_send = int(os.environ.get("GRPC_MAX_SEND_BYTES", 32 * 1024 * 1024))  # 32 MiB
    server = grpc.aio.server(options=[
        ("grpc.max_receive_message_length", max_recv),
        ("grpc.max_send_message_length",    max_send),
    ])

    # Register service with injected DB handles
    pb_grpc.add_InferenceServiceServicer_to_server(
        InferenceService(models_collection=models_collection, gridfs_bucket=gridfs_bucket),
        server,
    )

    addr = os.environ.get("GRPC_BIND", "[::]:50051")
    server.add_insecure_port(addr)
    await server.start()
    print(f"gRPC server listening on {addr}")

    # Sanity check: list deployed models from THIS DB
    await _debug_log_deployed_names(models_collection)

    try:
        await server.wait_for_termination()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        try:
            grace = float(os.environ.get("GRPC_GRACE_SECONDS", "5"))
            await asyncio.shield(server.stop(grace=grace))
        except asyncio.CancelledError:
            pass
        finally:
            client.close()


if __name__ == "__main__":
    asyncio.run(serve())