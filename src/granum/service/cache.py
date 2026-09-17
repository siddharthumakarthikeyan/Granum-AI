"""A small in-memory cache for media bytes."""

from __future__ import annotations

import threading
import time
from collections import OrderedDict


class ByteCache:
    """Size- and time-bounded LRU over bytes."""

    def __init__(self, max_bytes: int = 256 * 1024 * 1024, ttl_seconds: float = 300.0) -> None:
        self.max_bytes = max_bytes
        self.ttl_seconds = ttl_seconds
        self._entries: OrderedDict[str, tuple[bytes, float]] = OrderedDict()
        self._size = 0
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    def get(self, key: str) -> bytes | None:
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                self.misses += 1
                return None
            data, stored_at = entry
            if self.ttl_seconds and time.monotonic() - stored_at > self.ttl_seconds:
                del self._entries[key]
                self._size -= len(data)
                self.misses += 1
                return None
            self._entries.move_to_end(key)
            self.hits += 1
            return data

    def put(self, key: str, data: bytes) -> None:
        if len(data) > self.max_bytes:
            return
        with self._lock:
            if key in self._entries:
                self._size -= len(self._entries[key][0])
            self._entries[key] = (data, time.monotonic())
            self._entries.move_to_end(key)
            self._size += len(data)
            while self._size > self.max_bytes and self._entries:
                _, (evicted, _) = self._entries.popitem(last=False)
                self._size -= len(evicted)

    def clear(self) -> None:
        with self._lock:
            self._entries.clear()
            self._size = 0

    @property
    def size_bytes(self) -> int:
        return self._size

    def stats(self) -> dict[str, int | float]:
        total = self.hits + self.misses
        return {
            "entries": len(self._entries),
            "size_bytes": self._size,
            "hits": self.hits,
            "misses": self.misses,
            "hit_rate": (self.hits / total) if total else 0.0,
        }
