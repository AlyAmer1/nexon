"""Async gRPC inference server mirrored to the REST /infer/{model_name} endpoint."""

from __future__ import annotations

import asyncio
import functools
import logging
import os
import signal
import sys
import time
import uuid
from typing import Any, Optional

import grpc
import numpy as np

from dotenv import load_dotenv

# Generated stubs (top-level, installed via wheel)
import inference_pb2 as pb
import inference_pb2_grpc as pb_grpc

# gRPC health service
from grpc_health.v1 import health, health_pb2, health_pb2_grpc

# Shared orchestrator (REST + gRPC)
from shared.orchestrator import (
    InferenceOrchestrator,
    ModelNotFoundError,
    ModelNotDeployedError,
    InvalidInputError,
    PROTO_TO_NP,                 # centralized proto->numpy map
    DT_UNSPECIFIED_SENTINEL,     # derive from model
    DT_UNSUPPORTED_SENTINEL,     # explicitly unsupported over raw-bytes path
)

# Per-process Mongo/Motor
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

load_dotenv()  # find server/.env when run from repo root or ./server


# Logging configuration
RESET   = "\x1b[0m"
RED     = "\x1b[31m"
GREEN   = "\x1b[32m"
YELLOW  = "\x1b[33m"
MAGENTA = "\x1b[35m"

def color_code_name(name: str) -> str:
    """Render a gRPC status code name with ANSI colors for terminal readability.

    Args:
        name: Canonical gRPC status code name (e.g., ``OK``).

    Returns:
        The status string wrapped with color codes suited to the severity.
    """
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
        field_styles={"name": {"color": "blue"}},
    )
except Exception:
    logging.basicConfig(
        level=os.environ.get("LOGLEVEL", "INFO"),
        format="%(levelname)s: %(name)s | %(message)s",
    )

log = logging.getLogger("grpc_server")
logging.getLogger("model_cache").setLevel(logging.INFO)  # show HIT/MISS if MODEL_CACHE_LOG=1


# Dtype mappings for request and response payloads
NP_TO_PROTO = {
    np.dtype(np.float32): pb.DT_FLOAT32,
    np.dtype(np.float64): pb.DT_FLOAT64,
    np.dtype(np.int32):   pb.DT_INT32,
    np.dtype(np.int64):   pb.DT_INT64,
    np.dtype(np.bool_):   pb.DT_BOOL,
}
# PROTO_TO_NP and sentinels come from shared.orchestrator


def _fmt_shape(x) -> str:
    """Convert a shape-like value to a printable list representation.

    Args:
        x: Iterable describing tensor dimensions.

    Returns:
        String form of the dimensions; ``[]`` when the input cannot be iterated.
    """
    try:
        return str(list(x))
    except Exception:
        return "[]"


async def _debug_log_deployed_names(models_collection):
    """Log the deployed model names visible to this process.

    Args:
        models_collection: Motor collection that stores model deployment metadata.
    """
    try:
        names = []
        async for m in models_collection.find({"status": "Deployed"}):
            n = m.get("name")
            if n:
                names.append(n)
        log.info("Deployed models visible to gRPC: %s", names)
    except Exception as e:
        log.warning("Could not list deployed models: %s", e)


# Optional health probe logging interceptor
class HealthLogInterceptor(grpc.aio.ServerInterceptor):
    """Emit structured logs for gRPC health checks when logging is enabled."""
    def __init__(self, enabled: bool, logger: logging.Logger):
        """Initialize the interceptor with optional logging behavior.

        Args:
            enabled: If False, the interceptor returns handlers unchanged.
            logger: Destination for any emitted log entries.
        """
        self.enabled = enabled
        self.logger = logger

    async def intercept_service(self, continuation: Any, handler_call_details: Any):
        """Optionally log incoming health RPCs and forward the handler.

        Args:
            continuation: Callable that yields the RPC handler when awaited.
            handler_call_details: Metadata describing the inbound RPC call.

        Returns:
            The original or wrapped handler depending on the logging setting.
        """
        handler = await continuation(handler_call_details)
        if not self.enabled or handler is None:
            return handler
        m = getattr(handler_call_details, "method", None)
        if isinstance(m, str) and m in ("/grpc.health.v1.Health/Check", "/grpc.health.v1.Health/Watch"):
            self.logger.info("Health probe: %s", m)
        return handler


# gRPC service implementation
class InferenceService(pb_grpc.InferenceServiceServicer):
    """gRPC servicer that mirrors the REST inference contract via the orchestrator."""

    def __init__(self, models_collection, gridfs_bucket: AsyncIOMotorGridFSBucket):
        """Create the servicer with shared database-backed dependencies.

        Args:
            models_collection: Motor collection containing model deployment metadata.
            gridfs_bucket: GridFS bucket providing access to model binaries.
        """
        self._orch = InferenceOrchestrator(models_collection=models_collection, gridfs_bucket=gridfs_bucket)
        log.info("Orchestrator initialized.")

    async def Predict(self, request: pb.PredictRequest, context: grpc.aio.ServicerContext) -> pb.PredictReply:
        """Execute the Predict RPC using shared REST parity semantics.

        Args:
            request: PredictRequest carrying model name and tensor payload.
            context: gRPC context used to propagate status and metadata.

        Returns:
            PredictReply containing output[0] mapped to the protobuf tensor type.
        """
        request_id = uuid.uuid4().hex[:8]
        model_name = (request.model_name or "").strip()

        started = time.perf_counter()
        status = grpc.StatusCode.OK
        reason = ""     # human-readable cause for non-OK
        req_bytes = 0
        response_bytes = 0
        input_shape = "[]"
        output_shape = "[]"
        input_dtype_str = "?"

        try:
            if not model_name:
                status = grpc.StatusCode.INVALID_ARGUMENT
                reason = "model_name is empty"
                context.set_code(status)
                context.set_details("model_name must be non-empty.")
                return pb.PredictReply()

            request_tensor = request.input
            dims = list(request_tensor.dims)
            input_shape = _fmt_shape(dims)
            if not dims:
                status = grpc.StatusCode.INVALID_ARGUMENT
                reason = "missing dims"
                context.set_code(status)
                context.set_details("input.dims must be provided (non-empty).")
                return pb.PredictReply()

            tensor_bytes = request_tensor.tensor_content
            req_bytes = len(tensor_bytes)

            # Map proto enum -> NumPy (or sentinel)
            mapped_dtype = PROTO_TO_NP.get(request_tensor.data_type, DT_UNSUPPORTED_SENTINEL)
            if mapped_dtype is DT_UNSUPPORTED_SENTINEL:
                status = grpc.StatusCode.INVALID_ARGUMENT
                reason = "DT_STRING is not supported over raw tensor bytes."
                context.set_code(status)
                context.set_details(reason)
                return pb.PredictReply()

            if mapped_dtype is DT_UNSPECIFIED_SENTINEL:
                request_numpy_dtype: Optional[np.dtype] = None   # derive from model
            else:
                request_numpy_dtype = mapped_dtype                     # explicit request dtype
                input_dtype_str = str(request_numpy_dtype)

            # Orchestrated inference (resolve/cache/validate/run)
            try:
                inference_outputs = await self._orch.run_from_bytes(
                    model_name=model_name,
                    dims=dims,
                    raw_bytes=tensor_bytes,
                    provided_name=(request_tensor.name or ""),
                    request_dtype=request_numpy_dtype,
                )
            except ModelNotFoundError as e:
                status = grpc.StatusCode.NOT_FOUND
                reason = str(e)
                context.set_code(status)
                context.set_details(str(e))
                return pb.PredictReply()
            except ModelNotDeployedError as e:
                status = grpc.StatusCode.FAILED_PRECONDITION
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

            # Success: build ResponseTensor for output[0]
            output_array = np.asarray(inference_outputs[0])
            output_shape = _fmt_shape(output_array.shape)

            if output_array.dtype != np.bool_:
                output_array = output_array.astype(output_array.dtype.newbyteorder("<"), copy=False)
            output_array = np.ascontiguousarray(output_array)

            proto_dtype = (
                    NP_TO_PROTO.get(output_array.dtype)
                    or NP_TO_PROTO.get(output_array.dtype.newbyteorder("="))
                    or NP_TO_PROTO.get(output_array.dtype.newbyteorder("<"))
            )
            if proto_dtype is None:
                status = grpc.StatusCode.INTERNAL
                reason = f"unsupported output dtype: {output_array.dtype}"
                context.set_code(status)
                context.set_details(reason)
                return pb.PredictReply()

            response_tensor = pb.ResponseTensor()
            response_tensor.name = ""
            response_tensor.dims.extend(list(output_array.shape))
            response_tensor.tensor_content = output_array.tobytes(order="C")
            response_tensor.data_type = proto_dtype

            response_bytes = len(response_tensor.tensor_content)
            return pb.PredictReply(outputs=[response_tensor])

        finally:
            dur_ms = (time.perf_counter() - started) * 1000.0
            code = context.code() or status or grpc.StatusCode.OK
            code_str = color_code_name(code.name)
            suffix = f" ({reason})" if reason else ""
            log.info(
                "Predict %s%s model=%s in=%s -> out=%s dtype=%s dur=%.2fms bytes=req=%d rep=%d id=%s",
                code_str, suffix, model_name or "?", input_shape, output_shape, input_dtype_str,
                dur_ms, req_bytes, response_bytes, request_id
            )


# Server bootstrap logic
def _hard_exit(code: int = 1) -> None:
    """Terminate the process without waiting for asyncio cleanup handlers.

    Args:
        code: Exit status to propagate to the operating system.
    """
    try:
        os._exit(code)  # type: ignore[attr-defined]
    except Exception:
        sys.exit(code)

async def serve():
    """Start the gRPC inference server and manage its lifecycle.

    Returns:
        None. The coroutine runs until interrupted and orchestrates graceful shutdown.
    """
    mongo_uri = os.environ.get("NEXON_MONGO_URI", "mongodb://localhost:27017")
    mongo_db  = os.environ.get("NEXON_MONGO_DB",  "onnx_platform")

    client = AsyncIOMotorClient(mongo_uri)
    db = client[mongo_db]
    models_collection = db["models"]
    gridfs_bucket = AsyncIOMotorGridFSBucket(db)

    max_recv = int(os.environ.get("GRPC_MAX_RECV_BYTES", 32 * 1024 * 1024))
    max_send = int(os.environ.get("GRPC_MAX_SEND_BYTES", 32 * 1024 * 1024))

    log_health = os.environ.get("LOG_HEALTH", "1").lower() in ("1", "true", "yes", "on")
    interceptors = [HealthLogInterceptor(True, log)] if log_health else []

    server = grpc.aio.server(
        options=[
            ("grpc.max_receive_message_length", max_recv),
            ("grpc.max_send_message_length",    max_send),
        ],
        interceptors=interceptors,
    )

    pb_grpc.add_InferenceServiceServicer_to_server(
        InferenceService(models_collection=models_collection, gridfs_bucket=gridfs_bucket),
        server,
    )

    health_servicer = health.HealthServicer()
    fully_qualified_service = pb.DESCRIPTOR.services_by_name["InferenceService"].full_name
    health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
    health_servicer.set(fully_qualified_service, health_pb2.HealthCheckResponse.NOT_SERVING)
    health_pb2_grpc.add_HealthServicer_to_server(health_servicer, server)

    async def readiness_monitor(models_collection, health_service: health.HealthServicer):
        """Track database reachability and publish health status updates.

        Args:
            models_collection: Motor collection for executing ping commands.
            health_service: Health servicer that exposes readiness information.
        """
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
                health_service.set("", state)
                health_service.set(fully_qualified_service, state)
            except Exception:
                pass

            await asyncio.sleep(interval)

    readiness_task = asyncio.create_task(readiness_monitor(models_collection, health_servicer))

    try:
        if os.environ.get("ENABLE_REFLECTION", "0").lower() in ("1", "true", "yes", "on"):
            from grpc_reflection.v1alpha import reflection  # type: ignore
            service_names = [fully_qualified_service, health.SERVICE_NAME, reflection.SERVICE_NAME]
            reflection.enable_server_reflection(service_names, server)
            log.info("gRPC reflection enabled for: %s", service_names[0])
    except Exception as e:
        log.warning("Reflection not enabled: %s", e)

    addr = os.environ.get("GRPC_BIND", "[::]:50051")
    server.add_insecure_port(addr)

    loop = asyncio.get_running_loop()
    shutdown_event = asyncio.Event()
    shutting_down = {"value": False}

    def _begin_shutdown(sig: signal.Signals):
        """Initiate the two-phase shutdown sequence in response to a signal.

        Args:
            sig: Signal that triggered the shutdown.
        """
        if not shutting_down["value"]:
            shutting_down["value"] = True
            log.info("Signal %s received. Beginning graceful shutdown...", sig.name)
            shutdown_event.set()
        else:
            log.warning("Second %s received. Forcing exit.", sig.name)
            _hard_exit(1)

    for sig_ in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig_, functools.partial(_begin_shutdown, sig_))
        except NotImplementedError:
            signal.signal(sig_, lambda *_: _begin_shutdown(sig_))

    await server.start()
    log.info("gRPC server listening on %s", addr)

    debug_task = asyncio.create_task(_debug_log_deployed_names(models_collection))
    await shutdown_event.wait()

    try:
        try:
            health_servicer.set("", health_pb2.HealthCheckResponse.NOT_SERVING)
            health_servicer.set(fully_qualified_service, health_pb2.HealthCheckResponse.NOT_SERVING)
        except Exception:
            pass

        for task in (debug_task, readiness_task):
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
