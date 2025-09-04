# File: server/app/services/shared/model_cache.py
# Description: A shared, in-memory cache for ONNX inference sessions.

import functools
from typing import Optional
import onnxruntime as ort
from gridfs import GridFS
from bson import ObjectId

class ModelCache:
    """
    Manages an in-memory cache for ONNX Runtime inference sessions using a
    thread-safe LRU (Least Recently Used) policy. This is designed to be
    instantiated as a singleton within each service that needs it.

    This class is the implementation of the "Model Cache" component in the
    Level 3 System Architecture diagram and is a critical performance optimization.
    """

    def __init__(self, gridfs_db: GridFS, capacity: int = 128):
        """
        Initializes the cache.
        Args:
            gridfs_db: An active GridFS instance to load models from on a cache miss.
            capacity: The maximum number of inference sessions to store in memory.
        """
        if not isinstance(gridfs_db, GridFS):
            raise TypeError("gridfs_db must be an instance of gridfs.GridFS")

        self.gridfs = gridfs_db
        # We use functools.lru_cache as a ready-made, high-performance, and thread-safe
        # implementation of an LRU cache. It memoizes the results of _load_session.
        self._get_session_from_cache = functools.lru_cache(maxsize=capacity)(self._load_session)

    def _load_session(self, file_id_str: str) -> ort.InferenceSession:
        """
        Private method to load a model from GridFS and create an InferenceSession.
        This function is the one that gets memoized by lru_cache. A 'cache miss'
        triggers the execution of this code.

        Args:
            file_id_str: The string representation of the model's ObjectId in GridFS.
        Returns:
            An ONNX Runtime InferenceSession.
        Raises:
            FileNotFoundError: If the file_id is not found in GridFS.
            ValueError: If the model file is corrupted or not a valid ONNX model.
        """
        print(f"--- CACHE MISS --- Loading model from GridFS with file_id: {file_id_str}")
        try:
            file_id = ObjectId(file_id_str)
            if not self.gridfs.exists(file_id):
                raise FileNotFoundError(f"Model file with id {file_id_str} not found in GridFS.")

            model_file = self.gridfs.get(file_id)
            model_bytes = model_file.read()

            # This is the most computationally expensive step that we are caching.
            # Using specific providers can further optimize performance.
            providers = ['CPUExecutionProvider']
            session = ort.InferenceSession(model_bytes, providers=providers)
            return session
        except FileNotFoundError:
            # Re-raise to be handled by the calling service
            raise
        except Exception as e:
            # Catch potential onnxruntime errors from corrupted files
            raise ValueError(f"Failed to load ONNX model for file_id {file_id_str}: {e}")

    def get_session(self, file_id: str) -> Optional[ort.InferenceSession]:
        """
        Public method to retrieve an inference session from the cache.
        This is the primary method that services should call.

        Args:
            file_id: The string representation of the model's ObjectId in GridFS.
        Returns:
            The cached InferenceSession, or None if loading failed.
        """
        if not file_id or not isinstance(file_id, str):
            print("Error: Invalid file_id provided to get_session.")
            return None

        try:
            return self._get_session_from_cache(file_id)
        except (FileNotFoundError, ValueError) as e:
            print(f"Error retrieving session from cache: {e}")
            return None