# File: server/app/services/shared/model_cache.py
# Async ONNX InferenceSession cache backed by MongoDB GridFS (Motor).
from __future__ import annotations

import asyncio
import os
import time
import logging
from typing import Any, Dict, Tuple

from bson import ObjectId
import onnxruntime as ort

try:
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket  # type: ignore
except Exception:  # pragma: no cover
    AsyncIOMotorGridFSBucket = None  # for type checkers when Motor isn't installed


class ModelCache:
    """
    Async in-memory cache of ONNX Runtime InferenceSession keyed by GridFS file_id.

    - Key: GridFS file_id (ObjectId). Accepts str|ObjectId; normalized to ObjectId.
    - Storage: dict acting as LRU with 'last_used' timestamps.
    - Concurrency: per-key asyncio.Lock prevents duplicate concurrent loads.
    - Session creation: from bytes via onnxruntime.InferenceSession.
    - Tunables via env:
        * MODEL_CACHE_MAX (default 64)
        * MODEL_CACHE_TTL (default 0; 0 = no TTL)
        * ORT_INTRA_OP_THREADS (default 0)
        * ORT_INTER_OP_THREADS (default 0)
        * ORT_GRAPH_OPT_LEVEL (default 99)
        * MODEL_CACHE_LOG (default 0; 1 enables INFO/DEBUG logs)
    """

    def __init__(
            self,
            gridfs_db: Any,
            *,
            max_entries: int | None = None,
            ttl_seconds: int | None = None,
            providers: list[str] | None = None,
    ):
        if not hasattr(gridfs_db, "open_download_stream"):
            raise TypeError("gridfs_db must expose 'open_download_stream(file_id)' (Motor GridFS bucket).")
        if AsyncIOMotorGridFSBucket is not None and not isinstance(gridfs_db, AsyncIOMotorGridFSBucket):
            # Soft check only; allow fakes in tests
            pass

        self._fs = gridfs_db
        self._max = max_entries or int(os.environ.get("MODEL_CACHE_MAX", "64"))
        self._ttl = ttl_seconds or int(os.environ.get("MODEL_CACHE_TTL", "0"))
        self._providers = providers  # None -> ORT default
        self._cache: Dict[ObjectId, Tuple[ort.InferenceSession, float, float]] = {}
        self._locks: Dict[ObjectId, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        # Logging (off by default)
        self._log = logging.getLogger("model_cache")
        self._verbose = os.environ.get("MODEL_CACHE_LOG", "0") == "1"

        # Session options (reproducible experiments)
        so = ort.SessionOptions()
        so.intra_op_num_threads = int(os.environ.get("ORT_INTRA_OP_THREADS", "0"))
        so.inter_op_num_threads = int(os.environ.get("ORT_INTER_OP_THREADS", "0"))
        try:
            opt_level = int(os.environ.get("ORT_GRAPH_OPT_LEVEL", "99"))
            so.graph_optimization_level = opt_level
        except Exception:
            pass
        self._sess_options = so

    def _normalize_id(self, file_id: Any) -> ObjectId:
        if isinstance(file_id, ObjectId):
            return file_id
        try:
            return ObjectId(str(file_id))
        except Exception as e:
            raise ValueError(f"Invalid GridFS file_id '{file_id}': {e}") from e

    def _lock_for(self, oid: ObjectId) -> asyncio.Lock:
        lk = self._locks.get(oid)
        if lk is None:
            lk = self._locks[oid] = asyncio.Lock()
        return lk

    async def get_session(self, file_id: Any) -> ort.InferenceSession:
        oid = self._normalize_id(file_id)
        now = time.time()

        sess = await self._get_if_fresh(oid, now)
        if sess is not None:
            if self._verbose:
                self._log.info("CACHE HIT file_id=%s", oid)
            return sess

        lk = self._lock_for(oid)
        async with lk:
            sess = await self._get_if_fresh(oid, now)
            if sess is not None:
                if self._verbose:
                    self._log.info("CACHE HIT (post-lock) file_id=%s", oid)
                return sess

            # Miss → load
            if self._verbose:
                self._log.info("CACHE MISS file_id=%s — loading from GridFS...", oid)
            try:
                grid_out = await self._fs.open_download_stream(file_id=oid)
                model_bytes = await grid_out.read()
                if self._verbose:
                    self._log.debug("READ %d bytes for file_id=%s", len(model_bytes), oid)
            except Exception as e:
                raise RuntimeError(f"Failed to read model bytes from GridFS for {oid}: {e}") from e

            try:
                session = ort.InferenceSession(
                    model_bytes,
                    sess_options=self._sess_options,
                    providers=self._providers,
                )
            except Exception as e:
                raise RuntimeError(f"Failed to create InferenceSession for {oid}: {e}") from e

            async with self._global_lock:
                self._cache[oid] = (session, now, now)
                self._evict_if_needed(now=now)
            if self._verbose:
                self._log.info("CACHE LOAD COMPLETE file_id=%s", oid)

            return session

    async def _get_if_fresh(self, oid: ObjectId, now: float) -> ort.InferenceSession | None:
        tpl = self._cache.get(oid)
        if not tpl:
            return None
        session, loaded_at, last_used = tpl

        if self._ttl > 0 and (now - loaded_at) > self._ttl:
            async with self._global_lock:
                self._cache.pop(oid, None)
            if self._verbose:
                self._log.info("CACHE EXPIRED file_id=%s ttl=%ss", oid, self._ttl)
            return None

        async with self._global_lock:
            self._cache[oid] = (session, loaded_at, now)
        return session

    def _evict_if_needed(self, now: float) -> None:
        if self._max <= 0:
            return
        while len(self._cache) > self._max:
            oldest_oid = min(self._cache.items(), key=lambda kv: kv[1][2])[0]
            self._cache.pop(oldest_oid, None)
            if self._verbose:
                self._log.info("CACHE EVICT file_id=%s", oldest_oid)

    def invalidate(self, file_id: Any) -> None:
        oid = self._normalize_id(file_id)
        self._cache.pop(oid, None)
        if self._verbose:
            self._log.info("CACHE INVALIDATE file_id=%s", oid)

    def clear(self) -> None:
        self._cache.clear()
        if self._verbose:
            self._log.info("CACHE CLEAR all")