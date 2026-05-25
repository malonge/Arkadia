"""Unit tests for services/api/store.py."""

from __future__ import annotations

import threading
import time
from datetime import datetime, timezone

from services.api.store import SensorStore, StoreEntry


class TestStoreEntry:
    def test_default_received_at_is_utc(self):
        before = datetime.now(timezone.utc)
        entry = StoreEntry(payload={"sensor_id": "bme280"})
        after = datetime.now(timezone.utc)
        assert before <= entry.received_at <= after
        assert entry.received_at.tzinfo == timezone.utc


class TestSensorStore:
    def test_upsert_and_get(self):
        store = SensorStore()
        payload = {"sensor_id": "bme280", "readings": {"temperature_c": 21.5}}
        store.upsert("bme280", payload)
        entry = store.get("bme280")
        assert entry is not None
        assert entry.payload == payload

    def test_get_missing_returns_none(self):
        store = SensorStore()
        assert store.get("nonexistent") is None

    def test_upsert_replaces_existing_entry(self):
        store = SensorStore()
        store.upsert("bme280", {"temperature_c": 20.0})
        store.upsert("bme280", {"temperature_c": 21.0})
        entry = store.get("bme280")
        assert entry is not None
        assert entry.payload["temperature_c"] == 21.0

    def test_upsert_updates_received_at(self):
        store = SensorStore()
        store.upsert("bme280", {"v": 1})
        t1 = store.get("bme280").received_at

        time.sleep(0.01)

        store.upsert("bme280", {"v": 2})
        t2 = store.get("bme280").received_at

        assert t2 > t1

    def test_all_returns_all_entries(self):
        store = SensorStore()
        store.upsert("bme280", {"a": 1})
        store.upsert("scd40", {"b": 2})
        result = store.all()
        assert set(result.keys()) == {"bme280", "scd40"}

    def test_all_returns_copy(self):
        store = SensorStore()
        store.upsert("bme280", {"a": 1})
        snapshot = store.all()
        store.upsert("bme280", {"a": 999})
        assert snapshot["bme280"].payload["a"] == 1

    def test_len(self):
        store = SensorStore()
        assert len(store) == 0
        store.upsert("bme280", {})
        assert len(store) == 1
        store.upsert("scd40", {})
        assert len(store) == 2

    def test_concurrent_upserts_are_safe(self):
        store = SensorStore()
        errors: list[Exception] = []

        def writer(sensor_id: str, n: int) -> None:
            for i in range(n):
                try:
                    store.upsert(sensor_id, {"i": i})
                except Exception as exc:
                    errors.append(exc)

        threads = [
            threading.Thread(target=writer, args=(f"sensor_{j}", 200))
            for j in range(10)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(store) == 10

    def test_concurrent_reads_are_safe(self):
        store = SensorStore()
        for i in range(5):
            store.upsert(f"sensor_{i}", {"v": i})

        errors: list[Exception] = []

        def reader() -> None:
            for _ in range(500):
                try:
                    store.all()
                    store.get("sensor_0")
                except Exception as exc:
                    errors.append(exc)

        threads = [threading.Thread(target=reader) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
