import json

import pytest

from flight_service.app.cache import Cache


class DummyRedis:
    def __init__(self):
        self.store = {}
        self.deleted = []
        self.setex_calls = []

    def get(self, key):
        return self.store.get(key)

    def setex(self, key, ttl, value):
        self.setex_calls.append((key, ttl, value))
        self.store[key] = value

    def delete(self, key):
        self.deleted.append(key)
        self.store.pop(key, None)

    def scan_iter(self, match=None):
        for key in list(self.store.keys()):
            if match is None or _match(match, key):
                yield key


def _match(pattern, key):
    if pattern == "*":
        return True
    if pattern.endswith("*"):
        return key.startswith(pattern[:-1])
    return key == pattern


@pytest.mark.unit
def test_cache_miss_logs(caplog, monkeypatch):
    dummy = DummyRedis()
    monkeypatch.setattr(Cache, "_init_client", lambda self: dummy)
    cache = Cache()

    caplog.set_level("INFO")
    value = cache.get_json("missing")
    assert value is None
    assert any("cache miss" in record.message for record in caplog.records)


@pytest.mark.unit
def test_cache_hit_logs(caplog, monkeypatch):
    dummy = DummyRedis()
    dummy.store["k"] = json.dumps({"a": 1})
    monkeypatch.setattr(Cache, "_init_client", lambda self: dummy)
    cache = Cache()

    caplog.set_level("INFO")
    value = cache.get_json("k")
    assert value == {"a": 1}
    assert any("cache hit" in record.message for record in caplog.records)


@pytest.mark.unit
def test_cache_set_json_uses_ttl(monkeypatch):
    dummy = DummyRedis()
    monkeypatch.setattr(Cache, "_init_client", lambda self: dummy)
    monkeypatch.setenv("CACHE_TTL_SECONDS", "123")
    cache = Cache()

    cache.set_json("k", {"a": 1})
    assert dummy.setex_calls[0][0] == "k"
    assert dummy.setex_calls[0][1] == 123


@pytest.mark.unit
def test_cache_delete_pattern(monkeypatch):
    dummy = DummyRedis()
    dummy.store = {"search:1": "x", "search:2": "y", "other": "z"}
    monkeypatch.setattr(Cache, "_init_client", lambda self: dummy)
    cache = Cache()

    cache.delete_pattern("search:*")
    assert "search:1" in dummy.deleted
    assert "search:2" in dummy.deleted
    assert "other" not in dummy.deleted
