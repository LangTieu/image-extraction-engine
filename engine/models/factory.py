"""Shared model factory (D4): keyed lazy loading with a bounded LRU cache.

Heavy OCR/table models (Tesseract wrapper, PaddleOCR, Table Transformer) used
to be built per file in the worker and per pipeline instance in the table
stage. The factory shares one instance per :class:`ModelKey`, loads lazily on
first ``get()`` (at most once per key even under concurrency), keeps at most
``model_cache_max`` instances in memory (LRU eviction) and offers explicit
``release``/``release_all`` so the API can free RAM on shutdown.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import threading
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, TypeVar

T = TypeVar("T")


@dataclass(frozen=True)
class ModelKey:
    """Identity of a shared model instance."""

    engine: str
    variant: str
    device: str
    options_hash: str


def options_hash(options: Any) -> str:
    """Stable SHA-256 over a dataclass options object (or any JSON value)."""
    if dataclasses.is_dataclass(options) and not isinstance(options, type):
        payload = json.dumps(dataclasses.asdict(options), sort_keys=True)
    else:
        payload = json.dumps(options, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class _Entry:
    value: Any
    lock: threading.Lock
    loaded: bool = False
    error: BaseException | None = None


@dataclass
class ModelFactory:
    """Keyed lazy-load cache for heavy model instances."""

    max_live: int = 2
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _entries: OrderedDict[ModelKey, _Entry] = field(
        default_factory=OrderedDict, repr=False
    )
    _loads: int = 0
    _hits: int = 0

    def __post_init__(self) -> None:
        if self.max_live < 1:
            raise ValueError(f"max_live must be >= 1, got {self.max_live}")

    def get(self, key: ModelKey, loader: Callable[[], T]) -> T:
        """Return the shared instance for ``key``, loading it at most once.

        Concurrent ``get()`` calls on the same key block on a per-key lock so
        ``loader`` runs exactly once; its exception is not cached, so the next
        call retries.
        """
        with self._lock:
            entry = self._entries.get(key)
            if entry is None:
                entry = _Entry(value=None, lock=threading.Lock())
                self._entries[key] = entry
                self._evict_locked()
            else:
                self._entries.move_to_end(key)
        with entry.lock:
            if entry.loaded:
                with self._lock:
                    self._hits += 1
                    self._entries.move_to_end(key)
                return entry.value
            value = loader()
            entry.value = value
            entry.loaded = True
            entry.error = None
            with self._lock:
                self._loads += 1
            return value

    def _evict_locked(self) -> None:
        # Least-recently-used entries are dropped first; entries that another
        # thread holds mid-load keep their lock object until released.
        while len(self._entries) > self.max_live:
            self._entries.popitem(last=False)

    def release(self, key: ModelKey) -> None:
        """Drop the cached instance for ``key`` (the next ``get`` reloads)."""
        with self._lock:
            self._entries.pop(key, None)

    def release_all(self) -> None:
        """Drop every cached instance (used by the API shutdown hook)."""
        with self._lock:
            self._entries.clear()

    def stats(self) -> dict[str, int]:
        with self._lock:
            return {"loads": self._loads, "hits": self._hits, "live": len(self._entries)}


default_factory = ModelFactory()
