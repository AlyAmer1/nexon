# Async gRPC inference server using the shared orchestrator (parity with REST /infer/{model_name}).

from __future__ import annotations
import os
import sys
import asyncio
import logging
import time
import uuid
import numpy as np
import grpc
import signal
import functools
from typing import Any

from dotenv import load_dotenv

# Generated stubs (run as: python -m grpc_service.server)
from grpc_service.generated import inference_pb2 as pb
from grpc_service.generated import inference_pb2_grpc as pb_grpc

# gRPC health service
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

# Shared orchestrator (REST + gRPC)
from shared.orchestrator import (
    InferenceOrchestrator,
    ModelNotFoundError,
    ModelNotDeployedError,
    InvalidInputError,
)

# Per-process Mongo/Motor
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

load_dotenv()  # find server/.env when run from repo root or ./server


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


# --------------------- optional: health-probe logging ------------------------
class HealthLogInterceptor(grpc.aio.ServerInterceptor):
    """
    Logs incoming grpc.health.v1.Health checks when enabled via LOG_HEALTH.
    Passive (no handler wrapping) for broad grpcio compatibility.
    """
    def __init__(self, enabled: bool, logger: logging.Logger):
        self.enabled = enabled
        self.logger = logger

    async def intercept_service(self, continuation: Any, handler_call_details: Any):
        handler = await continuation(handler_call_details)
        if not self.enabled or handler is None:
            return handler
        # Some type stubs don't expose .method; use getattr to keep IDE happy.
        m = getattr(handler_call_details, "method", None)
        if isinstance(m, str) and m in ("/grpc.health.v1.Health/Check", "/grpc.health.v1.Health/Watch"):
            self.logger.info("Health probe: %s", m)
        return handler


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
                status = grpc.StatusCode.INTERNAL
                reason = f"unsupported output dtype: {out_arr.dtype}"
                context.set_code(status)
                context.set_details(reason)
                return pb.PredictReply()

            reply_t = pb.ResponseTensor()
            reply_t.name = ""
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
def _hard_exit(code: int = 1) -> None:
    """Force process exit without cleanup; fall back to sys.exit if unavailable."""
    try:
        os._exit(code)  # type: ignore[attr-defined]
    except Exception:
        sys.exit(code)

async def serve():
    """Start the async gRPC server and shut down cleanly on first SIGINT/SIGTERM."""
    mongo_uri = os.environ.get("NEXON_MONGO_URI", "mongodb://localhost:27017")
    mongo_db  = os.environ.get("NEXON_MONGO_DB",  "onnx_platform")

    client = AsyncIOMotorClient(mongo_uri)
    db = client[mongo_db]
    models_collection = db["models"]
    gridfs_bucket = AsyncIOMotorGridFSBucket(db)

    max_recv = int(os.environ.get("GRPC_MAX_RECV_BYTES", 32 * 1024 * 1024))
    max_send = int(os.environ.get("GRPC_MAX_SEND_BYTES", 32 * 1024 * 1024))

    # Opt-in health probe logging via env
    log_health = os.environ.get("LOG_HEALTH", "0").lower() in ("1", "true", "yes", "on")
    interceptors = [HealthLogInterceptor(True, log)] if log_health else []

    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", max_recv),
            ("grpc.max_send_message_length",    max_send),
        ],
        interceptors=interceptors,
    )

    # Register inference service
    pb_grpc.add_InferenceServiceServicer_to_server(
        InferenceService(models_collection=models_collection, gridfs_bucket=gridfs_bucket),
        server,
    )

    # Health service
    health_servicer = health.HealthServicer()
    # Start conservatively; readiness monitor will flip to SERVING when Mongo is reachable
    health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
    health_servicer.set("inference.InferenceService", health_pb2.HealthCheckResponse.NOT_SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

    # --- Readiness monitor: flip health based on Mongo ping ---
    async def readiness_monitor(models_collection, hs: health.HealthServicer):
        prev = None
        interval = int(os.environ.get("READINESS_INTERVAL", "5"))
        while True:
            try:
                await models_collection.database.command("ping")
                state = health_pb2.HealthCheckResponse.SERVING
            except Exception:
                state = health_pb2.HealthCheckResponse.NOT_SERVING

            if state != prev:
                label = "SERVING" if state == health_pb2.HealthCheckResponse.SERVING else "NOT_SERVING"
                log.info("Readiness (gRPC): %s", label)
                prev = state

            try:
                hs.set("", state)
                hs.set("inference.InferenceService", state)
            except Exception:
                pass

            await asyncio.sleep(interval)

    ready_task = asyncio.create_task(readiness_monitor(models_collection, health_servicer))

    # Optional: enable server reflection if available & requested
    try:
        if os.environ.get("ENABLE_REFLECTION", "0").lower() in ("1", "true", "yes", "on"):
            from grpc_reflection.v1alpha import reflection  # type: ignore
            # Use the fully-qualified service name from the generated descriptor
            fq_service = pb.DESCRIPTOR.services_by_name["InferenceService"].full_name
            service_names = [fq_service, health.SERVICE_NAME, reflection.SERVICE_NAME]
            reflection.enable_server_reflection(service_names, server)
            log.info("gRPC reflection enabled for: %s", service_names[0])
    except Exception as e:
        log.warning("Reflection not enabled: %s", e)

    addr = os.environ.get("GRPC_BIND", "[::]:50051")
    server.add_insecure_port(addr)

    # ---- signal handling (first ^C -> graceful; second ^C -> force) ----
    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    shutting_down = {"value": False}

    def _begin_shutdown(sig: signal.Signals):
        if not shutting_down["value"]:
            shutting_down["value"] = True
            log.info("Signal %s received. Beginning graceful shutdown…", sig.name)
            shutdown_event.set()
        else:
            log.warning("Second %s received. Forcing exit.", sig.name)
            _hard_exit(1)

    for sig_ in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_, functools.partial(_begin_shutdown, sig_))
        except NotImplementedError:
            signal.signal(sig_, lambda *_: _begin_shutdown(sig_))

    # ---- start & run ----
    await server.start()
    log.info("gRPC server listening on %s", addr)

    # best-effort: list deployed models (can be cancelled safely)
    dbg_task = asyncio.create_task(_debug_log_deployed_names(models_collection))

    # Wait until a signal arrives
    await shutdown_event.wait()

    # ---- graceful stop ----
    try:
        # Advertise NOT_SERVING so Envoy drains before we close connections
        try:
            health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
            health_servicer.set("inference.InferenceService", health_pb2.HealthCheckResponse.NOT_SERVING)
        except Exception:
            pass

        # Cancel background tasks
        for task in (dbg_task, ready_task):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        grace = float(os.environ.get("GRPC_GRACE_SECONDS", "5"))
        await server.stop(grace)
        await server.wait_for_termination()
    finally:
        try:
            client.close()
        except Exception:
            pass
        log.info("Shutdown complete.")


if __name__ == "__main__":
    asyncio.run(serve())