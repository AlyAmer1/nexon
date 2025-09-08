# File: server/app/services/database.py
# Purpose: Centralized MongoDB (Motor) + GridFS setup for both FastAPI and gRPC
# Notes:
#  - Auto-loads a shared .env (repo root or server/) if present.
#  - Accepts multiple env var spellings for compatibility.
#  - Exposes: client, db (and alias 'database'), models_collection, fs.

from __future__ import annotations

import os
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorGridFSBucket

# --- BEGIN: unified .env loading (non-fatal if python-dotenv is missing) ---
try:
    from dotenv import load_dotenv  # pip install python-dotenv
    _here = Path(__file__).resolve()
    # Try repo root: .../nexon/.env  and server dir: .../nexon/server/.env
    _candidates = []
    if len(_here.parents) >= 4:
        _candidates.append(_here.parents[3] / ".env")  # repo root
    if len(_here.parents) >= 3:
        _candidates.append(_here.parents[2] / ".env")  # server/

    for _env in _candidates:
        if _env and _env.exists():
            load_dotenv(_env, override=False)
except Exception:
    # If dotenv isn't installed or any issue occurs, just proceed with OS env
    pass
# --- END: unified .env loading ---

# --- BEGIN: standardized env keys with fallbacks ---
MONGODB_URI = (
        os.getenv("MONGODB_URI")
        or os.getenv("MONGODB_URL")
        or os.getenv("MONGO_URI")         # legacy
        or "mongodb://localhost:27017"
)

MONGODB_DB = (
        os.getenv("MONGODB_DB")
        or os.getenv("MONGO_DB")          # legacy
        or "onnx_platform"                        # sensible default used in your data
)
# --- END: standardized env keys with fallbacks ---

# Create Motor client and DB handle
client: AsyncIOMotorClient = AsyncIOMotorClient(MONGODB_URI)
db = client[MONGODB_DB]
database = db  # backward-compat alias

# Collections / buckets used across the app
models_collection = db["models"]
fs: AsyncIOMotorGridFSBucket = AsyncIOMotorGridFSBucket(db)

__all__ = [
    "MONGODB_URI",
    "MONGODB_DB",
    "client",
    "db",
    "database",
    "models_collection",
    "fs",
]