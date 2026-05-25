"""Integration-level tests for the API routes using FastAPI TestClient."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from services.api.routes import health as health_module
from services.api.routes import sensors as sensors_module
from services.api.routes import version as version_module
from services.api.store import SensorStore
from services.api.ws import AudioStreamBroadcaster

# ---------------------------------------------------------------------------
# Test-app factory (bypasses MQTT / lifespan)
# ---------------------------------------------------------------------------

_API_KEY = "test-secret-key"
_KNOWN_IDS = {"bme280", "scd40", "inmp441"}
_STALE_THRESHOLD = 120


def _make_app(
    store: SensorStore | None = None,
    api_key: str = _API_KEY,
    known_ids: set[str] | None = None,
    stale_threshold: int = _STALE_THRESHOLD,
) -> FastAPI:
    """Create a minimal FastAPI app wired to the given store, bypassing lifespan."""
    from starlette.middleware.base import BaseHTTPMiddleware
    from fastapi.responses import JSONResponse
    from fastapi import Request

    if store is None:
        store = SensorStore()
    if known_ids is None:
        known_ids = _KNOWN_IDS

    mock_mqtt = MagicMock()
    mock_mqtt.is_connected = True

    broadcaster = AudioStreamBroadcaster()

    app = FastAPI()

    class APIKeyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            if request.headers.get("upgrade", "").lower() == "websocket":
                return await call_next(request)
            exempt = {"/health", "/docs", "/openapi.json", "/redoc"}
            if request.url.path in exempt:
                return await call_next(request)
            expected = request.app.state.api_key
            provided = request.headers.get("X-API-Key", "")
            if provided != expected or not expected:
                return JSONResponse(status_code=401, content={"detail": "Unauthorized"})
            return await call_next(request)

    app.add_middleware(APIKeyMiddleware)

    app.include_router(health_module.router)
    app.include_router(version_module.router)
    app.include_router(sensors_module.router)

    app.state.store = store
    app.state.broadcaster = broadcaster
    app.state.mqtt_client = mock_mqtt
    app.state.api_key = api_key
    app.state.known_sensor_ids = known_ids
    app.state.stale_threshold_seconds = stale_threshold

    return app


def _client(app: FastAPI) -> TestClient:
    return TestClient(app, raise_server_exceptions=True)


# ---------------------------------------------------------------------------
# /health
# ---------------------------------------------------------------------------


class TestHealth:
    def test_health_returns_200_no_auth_required(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/health")
        assert r.status_code == 200

    def test_health_body_shape(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/health")
        body = r.json()
        assert "status" in body
        assert "broker_connected" in body
        assert "uptime_seconds" in body

    def test_health_broker_connected_true_when_connected(self):
        app = _make_app()
        app.state.mqtt_client.is_connected = True
        with _client(app) as c:
            r = c.get("/health")
        assert r.json()["broker_connected"] is True
        assert r.json()["status"] == "ok"

    def test_health_broker_connected_false_when_disconnected(self):
        app = _make_app()
        app.state.mqtt_client.is_connected = False
        with _client(app) as c:
            r = c.get("/health")
        assert r.json()["broker_connected"] is False
        assert r.json()["status"] == "degraded"

    def test_health_no_api_key_still_200(self):
        app = _make_app(api_key="secret")
        with _client(app) as c:
            r = c.get("/health")
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# /version
# ---------------------------------------------------------------------------


class TestVersion:
    def test_version_requires_api_key(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/version")
        assert r.status_code == 401

    def test_version_returns_200_with_key(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/version", headers={"X-API-Key": _API_KEY})
        assert r.status_code == 200

    def test_version_body_shape(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/version", headers={"X-API-Key": _API_KEY})
        body = r.json()
        assert body["service"] == "home-monitor-api"
        assert "version" in body
        assert "git_commit" in body

    def test_wrong_api_key_returns_401(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/version", headers={"X-API-Key": "wrong-key"})
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /sensors
# ---------------------------------------------------------------------------


class TestListSensors:
    def _headers(self):
        return {"X-API-Key": _API_KEY}

    def test_empty_store_returns_empty_dict(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors", headers=self._headers())
        assert r.status_code == 200
        assert r.json() == {}

    def test_returns_all_stored_sensors(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280", "readings": {"temperature_c": 21.5}})
        store.upsert("scd40", {"sensor_id": "scd40", "readings": {"co2_ppm": 420.0}})
        app = _make_app(store=store)
        with _client(app) as c:
            r = c.get("/sensors", headers=self._headers())
        body = r.json()
        assert set(body.keys()) == {"bme280", "scd40"}
        assert body["bme280"]["readings"]["temperature_c"] == 21.5

    def test_requires_api_key(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /sensors/{sensor_id}
# ---------------------------------------------------------------------------


class TestGetSensor:
    def _headers(self):
        return {"X-API-Key": _API_KEY}

    def test_returns_200_when_data_available(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        app = _make_app(store=store)
        with _client(app) as c:
            r = c.get("/sensors/bme280", headers=self._headers())
        assert r.status_code == 200
        assert r.json()["sensor_id"] == "bme280"

    def test_returns_404_for_unknown_sensor(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors/totally_unknown", headers=self._headers())
        assert r.status_code == 404

    def test_returns_503_for_known_sensor_with_no_data(self):
        app = _make_app()  # store is empty but bme280 is in known_ids
        with _client(app) as c:
            r = c.get("/sensors/bme280", headers=self._headers())
        assert r.status_code == 503

    def test_requires_api_key(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors/bme280")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# GET /sensors/{sensor_id}/status
# ---------------------------------------------------------------------------


class TestGetSensorStatus:
    def _headers(self):
        return {"X-API-Key": _API_KEY}

    def test_returns_200_with_correct_shape(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        app = _make_app(store=store)
        with _client(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._headers())
        assert r.status_code == 200
        body = r.json()
        assert body["sensor_id"] == "bme280"
        assert "last_seen" in body
        assert "seconds_since_update" in body
        assert "stale" in body
        assert "stale_threshold_seconds" in body

    def test_fresh_reading_is_not_stale(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        app = _make_app(store=store, stale_threshold=120)
        with _client(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._headers())
        assert r.json()["stale"] is False

    def test_old_reading_is_stale(self):
        store = SensorStore()
        store.upsert("bme280", {"sensor_id": "bme280"})
        entry = store.get("bme280")
        # Back-date the received_at timestamp
        entry.received_at = datetime.now(timezone.utc) - timedelta(seconds=200)
        app = _make_app(store=store, stale_threshold=120)
        with _client(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._headers())
        assert r.json()["stale"] is True

    def test_returns_404_for_unknown_sensor(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors/totally_unknown/status", headers=self._headers())
        assert r.status_code == 404

    def test_returns_503_for_known_sensor_with_no_data(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors/bme280/status", headers=self._headers())
        assert r.status_code == 503

    def test_requires_api_key(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors/bme280/status")
        assert r.status_code == 401


# ---------------------------------------------------------------------------
# API key middleware edge cases
# ---------------------------------------------------------------------------


class TestAPIKeyMiddleware:
    def test_missing_key_returns_401(self):
        app = _make_app()
        with _client(app) as c:
            r = c.get("/sensors")
        assert r.status_code == 401

    def test_empty_key_returns_401(self):
        app = _make_app(api_key="")
        with _client(app) as c:
            r = c.get("/sensors", headers={"X-API-Key": ""})
        assert r.status_code == 401

    def test_correct_key_passes(self):
        app = _make_app(api_key="my-key")
        with _client(app) as c:
            r = c.get("/sensors", headers={"X-API-Key": "my-key"})
        assert r.status_code == 200
