"""Tests for ConnectivityStore and the connectivity field in /sensors/{id}/status."""

from __future__ import annotations

import threading
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routes import health as health_module
from services.api.routes import sensors as sensors_module
from services.api.routes import version as version_module
from services.api.store import ConnectivityStore, SensorStore
from services.api.ws import AudioStreamBroadcaster

# ---------------------------------------------------------------------------
# ConnectivityStore unit tests
# ---------------------------------------------------------------------------

_API_KEY = "test-key"


class TestConnectivityStore:
    def test_unknown_by_default(self):
        cs = ConnectivityStore()
        assert cs.get("bme280") == "unknown"

    def test_update_online(self):
        cs = ConnectivityStore()
        cs.update("bme280", "online")
        assert cs.get("bme280") == "online"

    def test_update_offline(self):
        cs = ConnectivityStore()
        cs.update("bme280", "offline")
        assert cs.get("bme280") == "offline"

    def test_update_overwrites(self):
        cs = ConnectivityStore()
        cs.update("bme280", "online")
        cs.update("bme280", "offline")
        assert cs.get("bme280") == "offline"

    def test_independent_sensors(self):
        cs = ConnectivityStore()
        cs.update("bme280", "online")
        cs.update("scd40", "offline")
        assert cs.get("bme280") == "online"
        assert cs.get("scd40") == "offline"
        assert cs.get("inmp441") == "unknown"

    def test_all_returns_copy(self):
        cs = ConnectivityStore()
        cs.update("bme280", "online")
        snapshot = cs.all()
        cs.update("bme280", "offline")
        assert snapshot["bme280"] == "online"

    def test_thread_safe_concurrent_updates(self):
        cs = ConnectivityStore()
        errors: list[Exception] = []

        def updater(sensor_id: str, status: str, n: int) -> None:
            for _ in range(n):
                try:
                    cs.update(sensor_id, status)
                    cs.get(sensor_id)
                except Exception as exc:
                    errors.append(exc)

        threads = [
            threading.Thread(target=updater, args=(f"s{i}", "online", 300))
            for i in range(8)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors


# ---------------------------------------------------------------------------
# _make_status_handler unit tests
# ---------------------------------------------------------------------------


class TestMakeStatusHandler:
    def _handler(self, cs: ConnectivityStore):
        from services.api.main import _make_status_handler
        return _make_status_handler(cs)

    def test_online_status_stored(self):
        cs = ConnectivityStore()
        h = self._handler(cs)
        h("home/status/bme280", b'{"status": "online"}')
        assert cs.get("bme280") == "online"

    def test_offline_status_stored(self):
        cs = ConnectivityStore()
        h = self._handler(cs)
        h("home/status/bme280", b'{"status": "offline"}')
        assert cs.get("bme280") == "offline"

    def test_unknown_sensor_id_extracted_from_topic(self):
        cs = ConnectivityStore()
        h = self._handler(cs)
        h("home/status/inmp441", b'{"status": "online"}')
        assert cs.get("inmp441") == "online"

    def test_bad_json_is_ignored(self):
        cs = ConnectivityStore()
        h = self._handler(cs)
        h("home/status/bme280", b"not-json")
        assert cs.get("bme280") == "unknown"

    def test_unrecognised_status_is_ignored(self):
        cs = ConnectivityStore()
        h = self._handler(cs)
        h("home/status/bme280", b'{"status": "degraded"}')
        assert cs.get("bme280") == "unknown"

    def test_wrong_topic_prefix_is_ignored(self):
        cs = ConnectivityStore()
        h = self._handler(cs)
        h("home/sensors/climate/bme280", b'{"status": "online"}')
        assert cs.get("bme280") == "unknown"


# ---------------------------------------------------------------------------
# /sensors/{id}/status connectivity field — route tests
# ---------------------------------------------------------------------------


def _make_app(
    store: SensorStore | None = None,
    connectivity: ConnectivityStore | None = None,
    known_ids: set[str] | None = None,
) -> FastAPI:
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi.responses import JSONResponse
    from fastapi import Request

    if store is None:
        store = SensorStore()
    if connectivity is None:
        connectivity = ConnectivityStore()
    if known_ids is None:
        known_ids = {"bme280", "scd40", "inmp441"}

    mock_mqtt = MagicMock()
    mock_mqtt.is_connected = True

    app = FastAPI()

    class APIKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            exempt = {"/health", "/docs", "/openapi.json", "/redoc"}
            if request.url.path in exempt:
                return await call_next(request)
            provided = request.headers.get("X-API-Key", "")
            if provided != _API_KEY:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return await call_next(request)

    app.add_middleware(APIKeyMiddleware)
    app.include_router(health_module.router)
    app.include_router(version_module.router)
    app.include_router(sensors_module.router)

    app.state.store = store
    app.state.connectivity = connectivity
    app.state.broadcaster = AudioStreamBroadcaster()
    app.state.mqtt_client = mock_mqtt
    app.state.api_key = _API_KEY
    app.state.known_sensor_ids = known_ids
    app.state.stale_threshold_seconds = 120

    return app


class TestSensorStatusConnectivity:
    _H = {"X-API-Key": _API_KEY}

    def test_connectivity_unknown_by_default(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        app = _make_app(store=store)
        with TestClient(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._H)
        assert r.status_code == 200
        assert r.json()["connectivity"] == "unknown"

    def test_connectivity_online(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        cs = ConnectivityStore()
        cs.update("bme280", "online")
        app = _make_app(store=store, connectivity=cs)
        with TestClient(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._H)
        assert r.json()["connectivity"] == "online"

    def test_connectivity_offline(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        cs = ConnectivityStore()
        cs.update("bme280", "offline")
        app = _make_app(store=store, connectivity=cs)
        with TestClient(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._H)
        assert r.json()["connectivity"] == "offline"

    def test_status_response_includes_all_fields(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        cs = ConnectivityStore()
        cs.update("bme280", "online")
        app = _make_app(store=store, connectivity=cs)
        with TestClient(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._H)
        body = r.json()
        assert set(body.keys()) >= {
            "sensor_id",
            "last_seen",
            "seconds_since_update",
            "stale",
            "stale_threshold_seconds",
            "connectivity",
        }

    def test_different_sensors_have_independent_connectivity(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        store.upsert("scd40", {"sensor_id": "scd40"})
        cs = ConnectivityStore()
        cs.update("bme280", "online")
        cs.update("scd40", "offline")
        app = _make_app(store=store, connectivity=cs)
        with TestClient(app) as c:
            r1 = c.get("/sensors/bme280/status", headers=self._H)
            r2 = c.get("/sensors/scd40/status", headers=self._H)
        assert r1.json()["connectivity"] == "online"
        assert r2.json()["connectivity"] == "offline"
