"""MongoDB Atlas persistent storage client and dict-compatible store proxy.

Provides seamless persistence for users, sessions, resumes, interviews, and reports.
If MongoDB is unreachable (e.g. offline, testing, DNS restriction), it automatically
and safely falls back to in-memory storage so the application never breaks.
"""
from __future__ import annotations

import logging
import os
import socket
from typing import Any, Iterator, MutableMapping
from pymongo import MongoClient
from pymongo.errors import PyMongoError

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

log = logging.getLogger(__name__)

DB_NAME = os.getenv("MONGODB_DB", "interview_platform")
MONGODB_URI = os.getenv("MONGODB_URI", "")

_client: MongoClient | None = None
_db = None
_connected: bool | None = None


def _can_connect_external() -> bool:
    """Instant probe to check if outbound network/sockets are permitted."""
    targets = [("1.1.1.1", 443), ("8.8.8.8", 443), ("8.8.8.8", 53)]
    for host, port in targets:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.4)
            s.connect((host, port))
            s.close()
            return True
        except (PermissionError, OSError):
            continue
    return False


def get_mongo_db():
    """Return database instance if available, otherwise None."""
    global _client, _db, _connected
    if os.getenv("TESTING_ENV") == "1":
        return None
    if _connected is False:
        return None
    if _db is not None:
        return _db
    if not MONGODB_URI:
        _connected = False
        return None

    if not _can_connect_external():
        _connected = False
        log.info("External network unavailable. Operating in in-memory mode.")
        return None

    try:
        _client = MongoClient(
            MONGODB_URI,
            serverSelectionTimeoutMS=2000,
            connectTimeoutMS=2000,
            socketTimeoutMS=3000,
        )
        _client.admin.command("ping")
        _db = _client[DB_NAME]
        _connected = True
        log.info("Successfully connected to MongoDB Atlas database: %s", DB_NAME)
        return _db
    except Exception as exc:
        _connected = False
        log.warning("MongoDB connection unavailable (%s). Operating in in-memory mode.", exc)
        return None


class MongoStore(MutableMapping[str, Any]):
    """Dict-compatible collection store with MongoDB Atlas backing and in-memory cache fallback."""

    def __init__(self, collection_name: str, key_field: str = "id") -> None:
        self.collection_name = collection_name
        self.key_field = key_field
        self._cache: dict[str, Any] = {}
        self._initial_loaded = False

    def _coll(self):
        db = get_mongo_db()
        return db[self.collection_name] if db is not None else None

    def _sync(self) -> None:
        """Synchronize in-memory cache with the live MongoDB collection."""
        coll = self._coll()
        if coll is None:
            return
        try:
            live: dict[str, Any] = {}
            for doc in coll.find():
                doc.pop("_id", None)
                key = doc.get(self.key_field)
                if key is not None:
                    val = doc.get("value") if "value" in doc and len(doc) == 2 else doc
                    live[str(key)] = val
            self._cache.update(live)
            self._initial_loaded = True
        except PyMongoError as exc:
            log.warning("Error syncing collection %s: %s", self.collection_name, exc)

    def _ensure_loaded(self) -> None:
        if self._initial_loaded:
            return
        self._sync()

    def __getitem__(self, key: str) -> Any:
        self._ensure_loaded()
        if key in self._cache:
            return self._cache[key]
        coll = self._coll()
        if coll is not None:
            try:
                doc = coll.find_one({self.key_field: key}, {"_id": 0})
                if doc is not None:
                    val = doc.get("value") if "value" in doc and len(doc) == 2 else doc
                    self._cache[key] = val
                    return val
            except PyMongoError:
                pass
        raise KeyError(key)

    def __setitem__(self, key: str, value: Any) -> None:
        self._ensure_loaded()
        self._cache[key] = value
        coll = self._coll()
        if coll is not None:
            try:
                if isinstance(value, dict):
                    doc = dict(value)
                    doc[self.key_field] = key
                else:
                    doc = {self.key_field: key, "value": value}
                coll.replace_one({self.key_field: key}, doc, upsert=True)
            except PyMongoError as exc:
                log.warning("Failed to persist item %s to MongoDB %s: %s", key, self.collection_name, exc)

    def __delitem__(self, key: str) -> None:
        self._ensure_loaded()
        if key in self._cache:
            del self._cache[key]
        coll = self._coll()
        if coll is not None:
            try:
                coll.delete_one({self.key_field: key})
            except PyMongoError as exc:
                log.warning("Failed to delete item %s from MongoDB %s: %s", key, self.collection_name, exc)

    def __contains__(self, key: object) -> bool:
        self._ensure_loaded()
        if key in self._cache:
            return True
        coll = self._coll()
        if coll is not None and isinstance(key, str):
            try:
                return coll.count_documents({self.key_field: key}, limit=1) > 0
            except PyMongoError:
                pass
        return False

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def setdefault(self, key: str, default: Any = None) -> Any:
        if key in self:
            return self[key]
        self[key] = default
        return default

    def pop(self, key: str, *args: Any) -> Any:
        self._ensure_loaded()
        try:
            val = self[key]
            del self[key]
            return val
        except KeyError:
            if args:
                return args[0]
            raise

    def clear(self) -> None:
        self._cache.clear()
        self._initial_loaded = True
        if os.getenv("TESTING_ENV") == "1":
            coll = self._coll()
            if coll is not None:
                try:
                    coll.delete_many({})
                except PyMongoError as exc:
                    log.warning("Failed to clear MongoDB collection %s: %s", self.collection_name, exc)

    def __iter__(self) -> Iterator[str]:
        self._sync()
        return iter(list(self._cache.keys()))

    def __len__(self) -> int:
        self._sync()
        return len(self._cache)

    def values(self):
        self._sync()
        return self._cache.values()

    def items(self):
        self._sync()
        return self._cache.items()

    def keys(self):
        self._sync()
        return self._cache.keys()
