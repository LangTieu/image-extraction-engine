"""D4 tests: shared model factory with bounded lazy load."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

import pytest

from engine.models import ModelFactory, ModelKey, default_factory, options_hash


def _key(name: str) -> ModelKey:
    return ModelKey(engine=name, variant="v", device="cpu", options_hash="h")


@dataclass
class _Opts:
    a: int
    b: str


def test_same_key_loads_once() -> None:
    factory = ModelFactory(max_live=4)
    calls = []

    def loader() -> object:
        calls.append(1)
        return object()

    first = factory.get(_key("x"), loader)
    second = factory.get(_key("x"), loader)
    assert first is second
    assert len(calls) == 1
    stats = factory.stats()
    assert stats["loads"] == 1 and stats["hits"] == 1 and stats["live"] == 1


def test_different_keys_load_separately() -> None:
    factory = ModelFactory(max_live=4)
    a = factory.get(_key("a"), object)
    b = factory.get(_key("b"), object)
    assert a is not b
    assert factory.stats()["loads"] == 2
    # A different options_hash for the same engine is a different key too.
    other = ModelKey(engine="a", variant="v", device="cpu", options_hash="h2")
    assert factory.get(other, object) is not a


def test_loader_exception_not_cached() -> None:
    factory = ModelFactory(max_live=4)
    attempts = []

    def flaky() -> object:
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("transient")
        return object()

    with pytest.raises(RuntimeError):
        factory.get(_key("flaky"), flaky)
    ok = factory.get(_key("flaky"), flaky)  # retried, not a cached failure
    assert ok is not None
    assert len(attempts) == 2


def test_concurrent_get_loads_once() -> None:
    factory = ModelFactory(max_live=4)
    calls = []
    gate = threading.Barrier(4, timeout=5)
    loaded = threading.Event()

    def slow_loader() -> object:
        calls.append(1)
        try:
            gate.wait()  # all 4 threads arrive before the load finishes
        except threading.BrokenBarrierError:  # pragma: no cover
            pass
        loaded.set()
        time.sleep(0.05)  # keep the load window open
        return object()

    results: list[object] = []

    def worker() -> None:
        results.append(factory.get(_key("conc"), slow_loader))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
        time.sleep(0.02)
    loaded.wait(timeout=5)
    for t in threads:
        t.join(timeout=5)

    assert len(calls) == 1
    assert all(r is results[0] for r in results)


def test_lru_eviction_bounded() -> None:
    factory = ModelFactory(max_live=2)
    factory.get(_key("a"), object)
    factory.get(_key("b"), object)
    factory.get(_key("c"), object)  # evicts "a" (least recently used)
    assert factory.stats()["live"] == 2

    factory.get(_key("a"), object)  # reload after eviction
    assert factory.stats()["loads"] == 4

    factory.release_all()
    assert factory.stats()["live"] == 0


def test_lru_order_refreshed_on_get() -> None:
    factory = ModelFactory(max_live=2)
    sentinel = object()
    factory.get(_key("a"), lambda: sentinel)
    factory.get(_key("b"), lambda: sentinel)
    factory.get(_key("a"), lambda: sentinel)  # refresh "a"; "b" becomes LRU
    factory.get(_key("c"), lambda: sentinel)  # evicts "b", not "a"
    assert factory.stats()["live"] == 2
    assert factory.get(_key("a"), lambda: sentinel) is sentinel


def test_release_forces_reload() -> None:
    factory = ModelFactory(max_live=4)
    first = factory.get(_key("r"), object)
    factory.release(_key("r"))
    second = factory.get(_key("r"), object)
    assert first is not second
    assert factory.stats()["loads"] == 2


def test_options_hash_stable_and_sensitive() -> None:
    assert options_hash(_Opts(a=1, b="x")) == options_hash(_Opts(a=1, b="x"))
    assert options_hash(_Opts(a=1, b="x")) != options_hash(_Opts(a=2, b="x"))
    assert options_hash(_Opts(a=1, b="x")) != options_hash(_Opts(a=1, b="y"))


def test_default_factory_is_shared_singleton() -> None:
    from engine.models import factory as factory_module

    assert default_factory is factory_module.default_factory
    assert default_factory.max_live >= 1
    default_factory.release_all()


def test_apply_model_cache_max_applies_setting() -> None:
    """Startup helper pushes SERVICE_MODEL_CACHE_MAX onto the default factory."""
    from service.core import settings as settings_module
    from service.core.settings import apply_model_cache_max

    original = settings_module.settings.model_cache_max
    try:
        settings_module.settings.model_cache_max = 1
        assert apply_model_cache_max() == 1
        assert default_factory.max_live == 1
        settings_module.settings.model_cache_max = 0  # clamped to >= 1
        assert apply_model_cache_max() == 1
    finally:
        settings_module.settings.model_cache_max = original
        default_factory.release_all()


def test_apply_model_cache_max_is_idempotent() -> None:
    from service.core import settings as settings_module
    from service.core.settings import apply_model_cache_max

    value = apply_model_cache_max()
    assert value == max(1, settings_module.settings.model_cache_max)
    assert default_factory.max_live == value
