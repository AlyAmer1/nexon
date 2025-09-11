# File: server/grpc_service/grpc_server_async.py
# Async gRPC Inference server (strict parity with FastAPI /infer/{model_name})
from __future__ import annotations

import os
import asyncio
import logging
import time
import uuid
import numpy as np
import grpc

from dotenv import load_dotenv
load_dotenv()  # find server/.env from repo root or server/

# Generated stubs (run as: python -m grpc_service.grpc_server_async)
import inference_pb2 as pb
import inference_pb2_grpc as pb_grpc

# Project services
from app.services.shared.model_cache import ModelCache

# Per-process Mongo/Motor client & GridFS bucket
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

# --- Logging setup (no timestamp, level prefix with colon, color)
RESET = "\x1b[0m"
RED = "\x1b[31m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
MAGENTA = "\x1b[35m"

def color_code_name(name: str) -> str:
    # Colorize common gRPC codes
    if name == "OK":
        return f"{GREEN}{name}{RESET}"
    if name in ("INVALID_ARGUMENT", "FAILED_PRECONDITION", "OUT_OF_RANGE"):
        return f"{YELLOW}{name}{RESET}"
    if name in ("INTERNAL", "UNKNOWN", "UNAVAILABLE", "DEADLINE_EXCEEDED"):
        return f"{RED}{name}{RESET}"
    return f"{MAGENTA}{name}{RESET}"

try:
    import coloredlogs  # type: ignore
    coloredlogs.install(
        level=os.environ.get("LOGLEVEL", "INFO"),
        fmt="%(levelname)s: %(name)s | %(message)s",
        level_styles={
            "debug":    {"color": "blue"},
            "info":     {},
            "warning":  {"color": "yellow"},
            "error":    {"color": "red"},
            "critical": {"color": "red", "bold": True},
        },
        field_styles={
            "name": {"color": "blue"},
        },
    )
except Exception:
    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(levelname)s: %(name)s | %(message)s",
    )

log = logging.getLogger("grpc_server")
logging.getLogger("model_cache").setLevel(logging.INFO)  # cache emits HIT/MISS if MODEL_CACHE_LOG=1

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


def _fmt_shape(x) -> str:
    try:
        return str(list(x))
    except Exception:
        return "[]"


class InferenceService(pb_grpc.InferenceServiceServicer):
    """Implements Predict with strict parity: uses input[0], returns output[0]."""

    def __init__(self, models_collection, gridfs_bucket: AsyncIOMotorGridFSBucket):
        self._models = models_collection
        self.model_cache = ModelCache(gridfs_db=gridfs_bucket)
        log.info("ModelCache initialized.")

    async def Predict(self, request: pb.PredictRequest, context: grpc.aio.ServicerContext) -> pb.PredictReply:
        # Per-request log context
        req_id = uuid.uuid4().hex[:8]
        method = "Predict"
        model_name = (request.model_name or "").strip()
        started = time.perf_counter()
        status = grpc.StatusCode.OK
        req_bytes = 0
        rep_bytes = 0
        in_shape = "[]"
        out_shape = "[]"
        in_dtype_str = "?"

        try:
            if not model_name:
                status = grpc.StatusCode.INVALID_ARGUMENT
                context.set_code(status)
                context.set_details("model_name must be non-empty.")
                return pb.PredictReply()

            # --- Resolve deployed GridFS file_id (parity with REST) ---
            try:
                models = await self._models.find({"name": model_name}).to_list(None)
                file_id = None
                for m in models or []:
                    if m.get("status") == "Deployed":
                        file_id = str(m.get("file_id"))
                        break
                if file_id is None:
                    status = grpc.StatusCode.INVALID_ARGUMENT
                    context.set_code(status)
                    context.set_details(f"No model with name '{model_name}' is deployed.")
                    return pb.PredictReply()
            except Exception as e:
                status = grpc.StatusCode.INTERNAL
                log.exception("Error resolving model metadata")
                context.set_code(status)
                context.set_details(f"Server error while resolving model: {e}")
                return pb.PredictReply()

            # --- Session from cache ---
            try:
                session = await self.model_cache.get_session(file_id)
                if session is None:
                    status = grpc.StatusCode.INTERNAL
                    context.set_code(status)
                    context.set_details("Failed to load ONNX model from storage.")
                    return pb.PredictReply()
            except Exception as e:
                status = grpc.StatusCode.INTERNAL
                log.exception("Error loading session")
                context.set_code(status)
                context.set_details(f"Server error while loading session: {e}")
                return pb.PredictReply()

            # --- Validate & decode input tensor ---
            try:
                in_meta = session.get_inputs()[0]
                in_dtype = ONNX_TO_NP.get(in_meta.type)
                in_dtype_str = in_meta.type or "?"
                if in_dtype is None:
                    status = grpc.StatusCode.INVALID_ARGUMENT
                    context.set_code(status)
                    context.set_details(f"Unsupported ONNX input dtype: {in_meta.type}")
                    return pb.PredictReply()

                t = request.input
                dims = list(t.dims)
                in_shape = _fmt_shape(dims)
                if not dims:
                    status = grpc.StatusCode.INVALID_ARGUMENT
                    context.set_code(status)
                    context.set_details("Input dims must be provided (non-empty).")
                    return pb.PredictReply()

                buf = t.tensor_content
                req_bytes = len(buf)
                elem_size = 1 if in_dtype == np.dtype(np.bool_) else int(in_dtype.itemsize)
                expected_len = int(np.prod(dims)) * elem_size
                if len(buf) != expected_len:
                    status = grpc.StatusCode.INVALID_ARGUMENT
                    context.set_code(status)
                    context.set_details(
                        f"tensor_content size {len(buf)} != prod(dims) {int(np.prod(dims))} * elem_size {elem_size}"
                    )
                    return pb.PredictReply()

                # Reconstruct NumPy in row-major
                if in_dtype == np.dtype(np.bool_):
                    arr = np.frombuffer(buf, dtype=np.uint8).astype(np.bool_, copy=False).reshape(dims)
                else:
                    arr = np.frombuffer(buf, dtype=in_dtype).reshape(dims)

                # Enforce binding to input[0] (parity with REST)
                in_name = in_meta.name
                if t.name and t.name != in_name:
                    status = grpc.StatusCode.INVALID_ARGUMENT
                    context.set_code(status)
                    context.set_details(f"input.name '{t.name}' does not match model input[0] '{in_name}'.")
                    return pb.PredictReply()

                # --- Run inference: output[0] only (parity) ---
                out0 = session.get_outputs()[0].name
                out_arr = session.run([out0], {in_name: arr})[0]
                out_shape = _fmt_shape(out_arr.shape)

                # Build reply (encodes dtype for client)
                reply_tensor = self._to_response_tensor(out_arr, name=out0)
                rep_bytes = len(reply_tensor.tensor_content)
                return pb.PredictReply(outputs=[reply_tensor])

            except grpc.RpcError:
                raise
            except Exception as e:
                status = grpc.StatusCode.INTERNAL
                log.exception("Unexpected inference error")
                context.set_code(status)
                context.set_details(f"Inference error: {e}")
                return pb.PredictReply()

        finally:
            dur_ms = (time.perf_counter() - started) * 1000.0
            code = context.code() or status or grpc.StatusCode.OK
            code_str = color_code_name(code.name)

            # Concise, “Uvicorn-like” one-liner:
            # INFO: grpc_server | Predict OK model=... in=[..]->out=[..] dtype=.. dur=..ms bytes=req=.. rep=.. id=..
            log.info(
                "Predict %s model=%s in=%s -> out=%s dtype=%s dur=%.2fms bytes=req=%d rep=%d id=%s",
                code_str, model_name or "?", in_shape, out_shape, in_dtype_str, dur_ms, req_bytes, rep_bytes, req_id
            )

    def _to_response_tensor(self, arr: np.ndarray, name: str = "") -> pb.ResponseTensor:
        # Ensure contiguous row-major and little-endian bytes (bool has no endianness)
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
    mongo_db = os.environ.get("NEXON_MONGO_DB", "onnx_platform")  # default matches FastAPI

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

    pb_grpc.add_InferenceServiceServicer_to_server(
        InferenceService(models_collection=models_collection, gridfs_bucket=gridfs_bucket),
        server,
    )

    addr = os.environ.get("GRPC_BIND", "[::]:50051")
    server.add_insecure_port(addr)
    await server.start()
    print(f"gRPC server listening on {addr}")

    # Sanity: show what we can see in DB
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