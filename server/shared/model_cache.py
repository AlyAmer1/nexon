"""Async ONNX Runtime session cache backed by MongoDB GridFS (Motor)."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Any, Dict, Tuple

from bson import ObjectId
import onnxruntime as ort  # use qualified names to avoid stub/IDE issues

try:
    # Motor is optional at type-check time; we only *use* the GridFS bucket interface.
    from motor.motor_asyncio import AsyncIOMotorGridFSBucket  # type: ignore
except Exception:  # pragma: no cover
    AsyncIOMotorGridFSBucket = None  # helps static analyzers when Motor isn't present


# Aliases to keep type hints readable while still importing ort safely
OrtInferenceSession = ort.InferenceSession


class ModelCache:
    """
    Async in-memory cache of ONNX Runtime InferenceSessions keyed by GridFS file_id.

    Key points:
      - Key: GridFS file_id (ObjectId); str/bytes identifiers are normalized.
      - Storage: dict-based LRU with timestamps for eviction and TTL checks.
      - Concurrency: per-key asyncio.Lock prevents duplicate loads.
      - Session creation: instantiated from GridFS bytes using onnxruntime.InferenceSession.
      - Tunables (env):
          MODEL_CACHE_MAX (default 64)
          MODEL_CACHE_TTL (default 0; disabled)
          ORT_INTRA_OP_THREADS (default 0)
          ORT_INTER_OP_THREADS (default 0)
          ORT_GRAPH_OPT_LEVEL (default 99)
          MODEL_CACHE_LOG (default 0)
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
        # Soft check only; allow fakes/mocks in tests
        if AsyncIOMotorGridFSBucket is not None and not isinstance(gridfs_db, AsyncIOMotorGridFSBucket):
            pass

        self._fs = gridfs_db
        self._max = max_entries or int(os.environ.get("MODEL_CACHE_MAX", "64"))
        self._ttl = ttl_seconds or int(os.environ.get("MODEL_CACHE_TTL", "0"))
        self._providers = providers  # None -> ORT default
        self._cache: Dict[ObjectId, Tuple[OrtInferenceSession, float, float]] = {}
        self._locks: Dict[ObjectId, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

        # Logging (off by default)
        self._log = logging.getLogger("model_cache")
        self._verbose = os.environ.get("MODEL_CACHE_LOG", "0") == "1"

        # Session options (robust to missing stubs in IDEs)
        SessionOptionsCls = getattr(ort, "SessionOptions", None)
        if SessionOptionsCls is None:
            raise RuntimeError("onnxruntime.SessionOptions not found -- check your onnxruntime installation.")
        so = SessionOptionsCls()
        so.intra_op_num_threads = int(os.environ.get("ORT_INTRA_OP_THREADS", "0"))
        so.inter_op_num_threads = int(os.environ.get("ORT_INTER_OP_THREADS", "0"))
        try:
            opt_level = int(os.environ.get("ORT_GRAPH_OPT_LEVEL", "99"))
            # Some stubs do not advertise this attribute; it exists at runtime.
            so.graph_optimization_level = opt_level  # type: ignore[attr-defined]
        except Exception:
            pass
        self._sess_options = so

    @staticmethod
    def _normalize_id(file_id: Any) -> ObjectId:
        """Return a valid ObjectId for str/ObjectId input; raise on invalid."""
        if isinstance(file_id, ObjectId):
            return file_id
        try:
            return ObjectId(str(file_id))
        except Exception as e:
            raise ValueError(f"Invalid GridFS file_id '{file_id}': {e}") from e

    def _lock_for(self, oid: ObjectId) -> asyncio.Lock:
        """Return the per-model lock, creating it on demand."""
        lk = self._locks.get(oid)
        if lk is None:
            lk = self._locks[oid] = asyncio.Lock()
        return lk

    async def get_session(self, file_id: Any) -> OrtInferenceSession:
        """
        Return a cached ORT session for file_id, loading it from GridFS on a cache miss.
        Concurrent calls for the same file_id are serialized.
        """
        oid = self._normalize_id(file_id)
        now = time.time()

        sess = await self._get_if_fresh(oid, now)
        if sess is not None:
            if self._verbose:
                self._log.info("CACHE HIT file_id=%s", oid)
            return sess

        lk = self._lock_for(oid)
        async with lk:
            # Re-check after acquiring the per-key lock
            sess = await self._get_if_fresh(oid, now)
            if sess is not None:
                if self._verbose:
                    self._log.info("CACHE HIT (post-lock) file_id=%s", oid)
                return sess

            # Miss -> load
            if self._verbose:
                self._log.info("CACHE MISS file_id=%s -- loading from GridFS...", oid)
            grid_out = None
            try:
                grid_out = await self._fs.open_download_stream(file_id=oid)
                model_bytes = await grid_out.read()
                if self._verbose:
                    self._log.debug("READ %d bytes for file_id=%s", len(model_bytes), oid)
            except Exception as e:
                raise RuntimeError(f"Failed to read model bytes from GridFS for {oid}: {e}") from e
            finally:
                # Best-effort close; supports both async and sync close() implementations.
                try:
                    if grid_out is not None:
                        closer = getattr(grid_out, "close", None)
                        if callable(closer):
                            result = closer()
                            if asyncio.iscoroutine(result):
                                await result
                except Exception:
                    # Never let a close error mask the actual operation outcome.
                    if self._verbose:
                        self._log.debug("Ignoring GridFS close() error for file_id=%s", oid)

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

    async def _get_if_fresh(self, oid: ObjectId, now: float) -> OrtInferenceSession | None:
        """Return cached session if unexpired; otherwise purge and return None."""
        tpl = self._cache.get(oid)
        if not tpl:
            return None
        session, loaded_at, last_used = tpl

        # TTL check (0 = disabled)
        if self._ttl > 0 and (now - loaded_at) > self._ttl:
            async with self._global_lock:
                self._cache.pop(oid, None)
            if self._verbose:
                self._log.info("CACHE EXPIRED file_id=%s ttl=%ss", oid, self._ttl)
            return None

        # Touch LRU timestamp
        async with self._global_lock:
            self._cache[oid] = (session, loaded_at, now)
        return session

    def _evict_if_needed(self, now: float) -> None:
        """Evict least-recently-used entries until size <= max."""
        if self._max <= 0:
            return
        while len(self._cache) > self._max:
            # Find entry with the oldest 'last_used' (LRU)
            oldest_oid: ObjectId | None = None
            oldest_last_used = float("inf")
            for oid, (_sess, _loaded_at, last_used) in self._cache.items():
                if last_used < oldest_last_used:
                    oldest_last_used = last_used
                    oldest_oid = oid
            if oldest_oid is None:
                break
            self._cache.pop(oldest_oid, None)
            if self._verbose:
                self._log.info("CACHE EVICT file_id=%s", oldest_oid)

    def invalidate(self, file_id: Any) -> None:
        """Remove a single entry from the cache (best effort)."""
        oid = self._normalize_id(file_id)
        self._cache.pop(oid, None)
        if self._verbose:
            self._log.info("CACHE INVALIDATE file_id=%s", oid)

    def clear(self) -> None:
        """Clear the entire cache (best effort)."""
        self._cache.clear()
        if self._verbose:
            self._log.info("CACHE CLEAR all")
