# server/grpc_service/grpc_server_async.py
from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict

from grpc import aio as grpc_aio
import grpc
import numpy as np
import pymongo
import gridfs

from server.app.services.shared.model_cache import ModelCache
from . import inference_pb2 as pb
from . import inference_pb2_grpc as pb_grpc

log = logging.getLogger("nexon.grpc.async")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "nexon")
GRPC_BIND = os.getenv("GRPC_BIND", "[::]:50051")


def _tensor_to_numpy(t: pb.Tensor) -> np.ndarray:
    arr = np.asarray(list(t.data), dtype=np.float32)
    if t.shape:
        arr = arr.reshape(tuple(t.shape))
    return arr


def _numpy_to_tensor(name: str, arr: np.ndarray) -> pb.Tensor:
    out = pb.Tensor()
    out.name = name
    out.shape[:] = list(arr.shape)
    out.data[:] = list(arr.astype(np.float32).ravel())
    return out


def _run_inference_sync(session, feed: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    outputs = session.run(None, feed)
    output_names = [o.name for o in session.get_outputs()]
    return {name: np.asarray(val) for name, val in zip(output_names, outputs)}


class _AsyncModelCache:
    """Small async façade over the sync ModelCache so we keep one cache implementation."""
    def __init__(self, sync_cache: ModelCache):
        self._cache = sync_cache

    async def get_session(self, model_id: str):
        return await asyncio.to_thread(self._cache.get_session, model_id)


class InferenceServiceAsync(pb_grpc.InferenceServiceServicer):
    def __init__(self, cache: _AsyncModelCache):
        self._cache = cache

    async def Predict(self, request: pb.PredictRequest, context: grpc_aio.ServicerContext) -> pb.PredictResponse:
        model_id = (request.model_id or "").strip()
        if not model_id:
            await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "model_id is required")

        feed: Dict[str, np.ndarray] = {}
        for t in request.inputs:
            if not t.name:
                await context.abort(grpc.StatusCode.INVALID_ARGUMENT, "every tensor must have a name")
            feed[t.name] = _tensor_to_numpy(t)

        try:
            session = await self._cache.get_session(model_id)
            outputs = await asyncio.to_thread(_run_inference_sync, session, feed)
        except Exception as e:
            log.exception("Predict failed")
            await context.abort(grpc.StatusCode.INTERNAL, f"prediction failed: {e}")

        resp = pb.PredictResponse()
        for name, arr in outputs.items():
            resp.outputs.append(_numpy_to_tensor(name, arr))
        return resp


async def serve() -> None:
    client = pymongo.MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    fs = gridfs.GridFS(db)  # pass GridFS, not the DB

    sync_cache = ModelCache(fs)
    cache = _AsyncModelCache(sync_cache)

    server = grpc_aio.server()
    pb_grpc.add_InferenceServiceServicer_to_server(InferenceServiceAsync(cache), server)
    server.add_insecure_port(GRPC_BIND)

    log.info("gRPC (async) listening on %s; MongoDB=%s DB=%s", GRPC_BIND, MONGO_URI, MONGO_DB)
    await server.start()
    try:
        await server.wait_for_termination()
    except asyncio.CancelledError:
        log.info("Termination requested; shutting down...")
        await server.stop(grace=None)


if __name__ == "__main__":
    asyncio.run(serve())