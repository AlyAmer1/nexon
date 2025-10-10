"""Centralized MongoDB/Motor configuration shared between REST and gRPC surfaces."""

from __future__ import annotations

import os
import logging
from typing import Optional

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

# Load .env for local development (no effect in Docker unless env vars are missing).
try:
    from dotenv import load_dotenv, find_dotenv  # pip install python-dotenv
    # Do not override variables already provided by the shell or docker-compose.
    load_dotenv(find_dotenv(usecwd=True), override=False)
except Exception:
    pass  # python-dotenv is optional

log = logging.getLogger("database")

def _first_env(*keys: str, default: Optional[str] = None) -> Optional[str]:
    """Return the first non-empty environment value among keys, else default."""
    for key in keys:
        value = os.getenv(key)
        if value:
            return value
    return default

# Prefer NEXON_* (compose), then common aliases, then a Docker-friendly default.
MONGO_URI: str = _first_env(
    "NEXON_MONGO_URI", "MONGODB_URI", "MONGODB_URL", "MONGO_URI",
    default="mongodb://mongo:27017",  # service name in docker-compose
)
MONGO_DB: str = _first_env(
    "NEXON_MONGO_DB", "MONGODB_DB", "MONGO_DB",
    default="onnx_platform",
)

# Tunables with sane defaults
SERVER_SELECTION_TIMEOUT_MS = int(os.getenv("MONGO_SERVER_SELECTION_TIMEOUT_MS", "10000"))
UUID_REPRESENTATION = os.getenv("MONGO_UUID_REPRESENTATION", "standard")  # Motor/PyMongo option

# Redact credentials in logs.
def _redact(uri: str) -> str:
    """Mask credentials in a MongoDB URI."""
    try:
        if "@" in uri and "://" in uri:
            scheme, rest = uri.split("://", 1)
            auth_and_host = rest.split("@", 1)
            if len(auth_and_host) == 2:
                _, host = auth_and_host
                return f"{scheme}://***:***@{host}"
        return uri
    except Exception:
        return "<redacted>"

# Single global client for the process
client: AsyncIOMotorClient = AsyncIOMotorClient(
    MONGO_URI,
    serverSelectionTimeoutMS=SERVER_SELECTION_TIMEOUT_MS,
    uuidRepresentation=UUID_REPRESENTATION,
)
db = client[MONGO_DB]
database = db  # backward-compat alias

# Collections / buckets
models_collection = db["models"]
fs: AsyncIOMotorGridFSBucket = AsyncIOMotorGridFSBucket(db)

log.info("MongoDB connected (uri=%s, db=%s)", _redact(MONGO_URI), MONGO_DB)

# Small helper reused by readiness probes.
async def ping() -> bool:
    """Return True when MongoDB responds to ping command; False otherwise."""
    try:
        await db.command("ping")
        return True
    except Exception as e:
        log.warning("Mongo ping failed: %s", e)
        return False

__all__ = [
    "MONGO_URI",
    "MONGO_DB",
    "client",
    "db",
    "database",
    "models_collection",
    "fs",
    "ping",
]
