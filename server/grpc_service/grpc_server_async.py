# File: server/grpc_service/grpc_server_async.py
# Async gRPC inference server using the shared orchestrator (parity with REST /infer/{model_name}).

from __future__ import annotations
import os
import asyncio
import logging
import time
import uuid
import numpy as np
import grpc

from dotenv import load_dotenv
load_dotenv()  # find server/.env when run from repo root or ./server

# Generated stubs (run as: python -m grpc_service.grpc_server_async)
import inference_pb2 as pb
import inference_pb2_grpc as pb_grpc

# Shared orchestrator (REST + gRPC)
from app.services.shared.orchestrator import (
    InferenceOrchestrator,
    ModelNotFoundError,
    ModelNotDeployedError,
    InvalidInputError,
)

# Per-process Mongo/Motor
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket


# -------------------------- logging ------------------------------------------
RESET   = "\x1b[0m"
RED     = "\x1b[31m"
GREEN   = "\x1b[32m"
YELLOW  = "\x1b[33m"
MAGENTA = "\x1b[35m"

def color_code_name(name: str) -> str:
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
            "info":     {},                 # keep INFO plain white
            "warning":  {"color": "yellow"},
            "error":    {"color": "red"},
            "critical": {"color": "red", "bold": True},
        },
        field_styles={
            "name": {"color": "blue"},      # logger name in blue (grpc_server, model_cache)
        },
    )
except Exception:
    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(levelname)s: %(name)s | %(message)s",
    )

log = logging.getLogger("grpc_server")
logging.getLogger("model_cache").setLevel(logging.INFO)  # show HIT/MISS if MODEL_CACHE_LOG=1


# ---------------------- dtype map for reply ----------------------------------
NP_TO_PROTO = {
    np.dtype(np.float32): pb.DT_FLOAT32,
    np.dtype(np.float64): pb.DT_FLOAT64,
    np.dtype(np.int32):   pb.DT_INT32,
    np.dtype(np.int64):   pb.DT_INT64,
    np.dtype(np.bool_):   pb.DT_BOOL,
}


def _fmt_shape(x) -> str:
    try:
        return str(list(x))
    except Exception:
        return "[]"


async def _debug_log_deployed_names(models_collection):
    """Best-effort: list deployed model names visible to this process."""
    try:
        names = []
        async for m in models_collection.find({"status": "Deployed"}):
            n = m.get("name")
            if n:
                names.append(n)
        log.info("Deployed models visible to gRPC: %s", names)
    except Exception as e:
        log.warning("Could not list deployed models: %s", e)


# --------------------------- gRPC service ------------------------------------
class InferenceService(pb_grpc.InferenceServiceServicer):
    """
    Unary Predict contract (parity with REST):
      - resolve model by *name*, require exactly one doc with status="Deployed"
      - decode RequestTensor (dims + raw bytes), optional input name
      - bind to model input[0]; return only output[0]
      - orchestrator enforces dtype/shape/name and uses the shared ModelCache
    """

    def __init__(self, models_collection, gridfs_bucket: AsyncIOMotorGridFSBucket):
        self._orch = InferenceOrchestrator(models_collection=models_collection, gridfs_bucket=gridfs_bucket)
        log.info("Orchestrator initialized.")

    async def Predict(self, request: pb.PredictRequest, context: grpc.aio.ServicerContext) -> pb.PredictReply:
        req_id = uuid.uuid4().hex[:8]
        model_name = (request.model_name or "").strip()

        started = time.perf_counter()
        status = grpc.StatusCode.OK
        reason = ""     # will hold a short human-readable cause for non-OK
        req_bytes = 0
        rep_bytes = 0
        in_shape = "[]"
        out_shape = "[]"
        in_dtype_str = "?"  # not always available cheaply; left as meta only

        try:
            # ---- validate model name ----
            if not model_name:
                status = grpc.StatusCode.INVALID_ARGUMENT
                reason = "model_name is empty"
                context.set_code(status)
                context.set_details("model_name must be non-empty.")
                return pb.PredictReply()

            # ---- decode request tensor envelope ----
            t = request.input
            dims = list(t.dims)
            in_shape = _fmt_shape(dims)
            if not dims:
                status = grpc.StatusCode.INVALID_ARGUMENT
                reason = "missing dims"
                context.set_code(status)
                context.set_details("input.dims must be provided (non-empty).")
                return pb.PredictReply()

            buf = t.tensor_content
            req_bytes = len(buf)

            # ---- orchestrated inference (covers: resolve, cache, dtype/shape/name) ----
            try:
                # tensor_name is optional; if provided, orchestrator enforces equality with input[0].name
                outs = await self._orch.run_from_bytes(
                    model_name=model_name,
                    dims=dims,
                    raw_bytes=buf,
                    provided_name=(t.name or "")
                )
            except ModelNotFoundError as e:
                status = grpc.StatusCode.NOT_FOUND
                reason = str(e)
                context.set_code(status)
                context.set_details(str(e))
                return pb.PredictReply()
            except ModelNotDeployedError as e:
                status = grpc.StatusCode.INVALID_ARGUMENT
                reason = str(e)
                context.set_code(status)
                context.set_details(str(e))
                return pb.PredictReply()
            except InvalidInputError as e:
                # Covers: unsupported dtype, size mismatch, shape mismatch, name mismatch, bad cast
                status = grpc.StatusCode.INVALID_ARGUMENT
                reason = str(e)
                context.set_code(status)
                context.set_details(str(e))
                return pb.PredictReply()
            except Exception as e:
                status = grpc.StatusCode.INTERNAL
                reason = f"internal: {e}"
                log.exception("Unexpected orchestrator error")
                context.set_code(status)
                context.set_details(f"Inference error: {e}")
                return pb.PredictReply()

            # ---- success: build single ResponseTensor (output[0]) ----
            out_arr = np.asarray(outs[0])
            out_shape = _fmt_shape(out_arr.shape)

            # Ensure little-endian row-major for transport
            if out_arr.dtype != np.bool_:
                out_arr = out_arr.astype(out_arr.dtype.newbyteorder("<"), copy=False)
            out_arr = np.ascontiguousarray(out_arr)

            proto_dt = (
                    NP_TO_PROTO.get(out_arr.dtype)
                    or NP_TO_PROTO.get(out_arr.dtype.newbyteorder("="))
                    or NP_TO_PROTO.get(out_arr.dtype.newbyteorder("<"))
            )
            if proto_dt is None:
                # Very rare: ORT produced a dtype we don't advertise
                status = grpc.StatusCode.INTERNAL
                reason = f"unsupported output dtype: {out_arr.dtype}"
                context.set_code(status)
                context.set_details(reason)
                return pb.PredictReply()

            # Use output[0] name for completeness
            reply_t = pb.ResponseTensor()
            reply_t.name = ""  # optional; clients generally don't require the name
            reply_t.dims.extend(list(out_arr.shape))
            reply_t.tensor_content = out_arr.tobytes(order="C")
            reply_t.data_type = proto_dt

            rep_bytes = len(reply_t.tensor_content)
            return pb.PredictReply(outputs=[reply_t])

        finally:
            dur_ms = (time.perf_counter() - started) * 1000.0
            code = context.code() or status or grpc.StatusCode.OK
            code_str = color_code_name(code.name)
            suffix = f" ({reason})" if reason else ""
            log.info(
                "Predict %s%s model=%s in=%s -> out=%s dtype=%s dur=%.2fms bytes=req=%d rep=%d id=%s",
                code_str, suffix, model_name or "?", in_shape, out_shape, in_dtype_str,
                dur_ms, req_bytes, rep_bytes, req_id
            )


# ------------------------------ server boot ----------------------------------
async def serve():
    """Start the async gRPC server and shut down cleanly on exit."""
    mongo_uri = os.environ.get("NEXON_MONGO_URI", "mongodb://localhost:27017")
    mongo_db  = os.environ.get("NEXON_MONGO_DB",  "onnx_platform")

    client = AsyncIOMotorClient(mongo_uri)
    db = client[mongo_db]
    models_collection = db["models"]
    gridfs_bucket = AsyncIOMotorGridFSBucket(db)

    max_recv = int(os.environ.get("GRPC_MAX_RECV_BYTES", 32 * 1024 * 1024))
    max_send = int(os.environ.get("GRPC_MAX_SEND_BYTES", 32 * 1024 * 1024))
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

    # sanity: visible deployed names (helps catch DB/URI mismatches)
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