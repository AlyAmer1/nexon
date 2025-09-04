# server/grpc_service/grpc_server.py
from __future__ import annotations

import logging
import os
from concurrent import futures
from typing import Dict

import grpc
import numpy as np
import pymongo
import gridfs

from server.app.services.shared.model_cache import ModelCache
from . import inference_pb2 as pb
from . import inference_pb2_grpc as pb_grpc

log = logging.getLogger("nexon.grpc.sync")
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


def _run_inference(session, feed: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
    """
    Minimal helper to execute ONNX Runtime session and return a dict[name -> np.ndarray].
    Assumes `session.run(None, feed)` returns outputs in the same order as `session.get_outputs()`.
    """
    ort_outputs = session.run(None, feed)
    output_names = [o.name for o in session.get_outputs()]
    return {name: np.asarray(val) for name, val in zip(output_names, ort_outputs)}


class InferenceService(pb_grpc.InferenceServiceServicer):
    def __init__(self, cache: ModelCache):
        self._cache = cache

    def Predict(self, request: pb.PredictRequest, context: grpc.ServicerContext) -> pb.PredictResponse:
        model_id = (request.model_id or "").strip()
        if not model_id:
            context.abort(grpc.StatusCode.INVALID_ARGUMENT, "model_id is required")

        feed: Dict[str, np.ndarray] = {}
        for t in request.inputs:
            if not t.name:
                context.abort(grpc.StatusCode.INVALID_ARGUMENT, "every tensor must have a name")
            feed[t.name] = _tensor_to_numpy(t)

        try:
            session = self._cache.get_session(model_id)
            outputs = _run_inference(session, feed)
        except Exception as e:
            log.exception("Predict failed")
            context.abort(grpc.StatusCode.INTERNAL, f"prediction failed: {e}")

        resp = pb.PredictResponse()
        for name, arr in outputs.items():
            resp.outputs.append(_numpy_to_tensor(name, arr))
        return resp


def serve() -> None:
    client = pymongo.MongoClient(MONGO_URI)
    db = client[MONGO_DB]
    fs = gridfs.GridFS(db)  # pass GridFS, not the DB
    cache = ModelCache(fs)

    server = grpc.server(futures.ThreadPoolExecutor(max_workers=os.cpu_count() or 8))
    pb_grpc.add_InferenceServiceServicer_to_server(InferenceService(cache), server)
    server.add_insecure_port(GRPC_BIND)

    log.info("gRPC (sync) listening on %s; MongoDB=%s DB=%s", GRPC_BIND, MONGO_URI, MONGO_DB)
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()