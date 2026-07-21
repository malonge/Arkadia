"""Arkadia API service — FastAPI app, MQTT subscriber, HTTP/WebSocket bridge."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.staticfiles import StaticFiles

# Resolve repo root so the common package is importable when this file is
# executed directly from its own directory.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.config import load_config  # noqa: E402
from common.mqtt import MQTTClient, configure_logging  # noqa: E402
from services.api.store import ConnectivityStore, SensorStore  # noqa: E402
from services.api.ws import AudioStreamBroadcaster  # noqa: E402

from services.api.routes import health as health_module  # noqa: E402
from services.api.routes import sensors as sensors_module  # noqa: E402
from services.api.routes import version as version_module  # noqa: E402
from services.api.routes import audio as audio_module  # noqa: E402

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

_CONFIG_PATH = Path(__file__).parent / "config.toml"
_WEB_DIST    = _REPO_ROOT / "web" / "dist"


def _load_api_config() -> dict[str, Any]:
    return load_config(_CONFIG_PATH)


# ---------------------------------------------------------------------------
# MQTT message handler
# ---------------------------------------------------------------------------

_STREAM_SUFFIX = "/stream"
_STATUS_PREFIX = "home/status/"


def _make_message_handler(
    store: SensorStore,
    broadcaster: AudioStreamBroadcaster,
) -> Any:
    def on_message(topic: str, payload: bytes) -> None:
        try:
            data: dict[str, Any] = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "Received non-JSON payload on topic %s; ignoring",
                topic,
                extra={"event": "mqtt_bad_payload"},
            )
            return

        if topic.endswith(_STREAM_SUFFIX):
            broadcaster.broadcast(payload.decode("utf-8"))
            return

        sensor_id = data.get("sensor_id")
        if not sensor_id:
            logger.warning(
                "Payload on topic %s missing sensor_id; ignoring",
                topic,
                extra={"event": "mqtt_missing_sensor_id"},
            )
            return

        store.upsert(sensor_id, data)
        logger.debug(
            "Stored reading for sensor %s from topic %s",
            sensor_id,
            topic,
            extra={"event": "sensor_reading_stored"},
        )

    return on_message


def _make_status_handler(connectivity: ConnectivityStore) -> Any:
    """Return a callback that updates connectivity status from ``home/status/#`` messages."""

    def on_status(topic: str, payload: bytes) -> None:
        # Derive sensor_id from the topic: "home/status/<sensor_id>"
        sensor_id = topic[len(_STATUS_PREFIX):] if topic.startswith(_STATUS_PREFIX) else ""
        if not sensor_id:
            return

        try:
            data: dict[str, Any] = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            logger.warning(
                "Non-JSON status payload on topic %s; ignoring",
                topic,
                extra={"event": "mqtt_bad_payload"},
            )
            return

        raw_status = data.get("status", "")
        if raw_status not in ("online", "offline"):
            logger.warning(
                "Unrecognised status %r for sensor %s; ignoring",
                raw_status,
                sensor_id,
                extra={"event": "mqtt_bad_status"},
            )
            return

        connectivity.update(sensor_id, raw_status)  # type: ignore[arg-type]
        logger.info(
            "Sensor %s is %s",
            sensor_id,
            raw_status,
            extra={"event": f"sensor_{raw_status}"},
        )

    return on_status


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------


@asynccontextmanager
async def _lifespan(app: FastAPI):
    cfg = _load_api_config()
    log_cfg = cfg.get("logging", {})
    configure_logging(
        level=log_cfg.get("level", "INFO"),
        fmt=log_cfg.get("format", "json"),
    )
    logger.info("API service starting", extra={"event": "service_starting"})

    broker_cfg = cfg.get("broker", {})
    mqtt_cfg = cfg.get("mqtt", {})
    sensor_cfg = cfg.get("sensors", {})
    auth_cfg = cfg.get("auth", {})

    api_key_env = auth_cfg.get("api_key_env", "MONITOR_API_KEY")
    api_key = os.environ.get(api_key_env, "")
    if not api_key:
        logger.warning(
            "API key env var %s is not set; all authenticated requests will be rejected",
            api_key_env,
            extra={"event": "api_key_missing"},
        )

    store = SensorStore()
    connectivity = ConnectivityStore()
    broadcaster = AudioStreamBroadcaster()
    broadcaster.set_loop(asyncio.get_event_loop())

    mqtt_client = MQTTClient(
        client_id=mqtt_cfg.get("client_id", "api-service"),
        broker_host=broker_cfg.get("host", "localhost"),
        broker_port=broker_cfg.get("port", 1883),
        keepalive=broker_cfg.get("keepalive", 60),
    )

    sensor_subscription = mqtt_cfg.get("subscription", "home/sensors/#")
    status_subscription = mqtt_cfg.get("status_subscription", "home/status/#")
    mqtt_client.subscribe(sensor_subscription, _make_message_handler(store, broadcaster), qos=1)
    mqtt_client.subscribe(status_subscription, _make_status_handler(connectivity), qos=1)

    try:
        mqtt_client.connect()
        mqtt_client.loop_start()
        logger.info(
            "MQTT client started; subscribed to %s and %s",
            sensor_subscription,
            status_subscription,
            extra={"event": "mqtt_subscribed"},
        )
    except Exception:
        logger.exception(
            "Failed to connect to MQTT broker; API will start without broker",
            extra={"event": "mqtt_connect_error"},
        )

    known_ids_raw = sensor_cfg.get("known_ids", ["bme280", "scd40", "sgp40", "inmp441"])
    app.state.store = store
    app.state.connectivity = connectivity
    app.state.broadcaster = broadcaster
    app.state.mqtt_client = mqtt_client
    app.state.api_key = api_key
    app.state.known_sensor_ids = set(known_ids_raw)
    app.state.stale_threshold_seconds = sensor_cfg.get("stale_threshold_seconds", 120)  # 2× the slowest sensor interval

    logger.info("API service started", extra={"event": "service_started"})
    yield

    logger.info("API service shutting down", extra={"event": "service_stopping"})
    mqtt_client.loop_stop()
    mqtt_client.disconnect()


# ---------------------------------------------------------------------------
# API key middleware
# ---------------------------------------------------------------------------

_EXEMPT_API_PATHS = {"/api/health", "/api/docs", "/api/openapi.json", "/api/redoc"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    """Validate the X-API-Key header on all non-exempt API routes.

    Static file requests (any path not starting with ``/api``) pass through
    without authentication so the browser can load the dashboard freely.
    WebSocket auth is handled inside the route handler via the ``api_key``
    query parameter.
    """

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path

        # WebSocket upgrades are authenticated in the route handler.
        if request.headers.get("upgrade", "").lower() == "websocket":
            return await call_next(request)

        # Non-API paths serve the static dashboard — no auth required.
        if not path.startswith("/api"):
            return await call_next(request)

        # A small set of API paths are public (health check, docs).
        if path in _EXEMPT_API_PATHS:
            return await call_next(request)

        expected: str = request.app.state.api_key
        provided = request.headers.get("X-API-Key", "")
        if provided != expected or not expected:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        return await call_next(request)


# ---------------------------------------------------------------------------
# App assembly
# ---------------------------------------------------------------------------


def create_app() -> FastAPI:
    app = FastAPI(title="Arkadia API", lifespan=_lifespan)

    app.add_middleware(APIKeyMiddleware)

    # All API routes live under /api so the root path is free for the
    # static file mount.
    app.include_router(health_module.router,   prefix="/api")
    app.include_router(version_module.router,  prefix="/api")
    app.include_router(sensors_module.router,  prefix="/api")
    app.include_router(audio_module.router,    prefix="/api")

    # Serve the built Svelte dashboard from web/dist/ at /.
    # Must be mounted LAST so /api/* routes are matched first.
    # html=True makes every unknown path fall back to index.html,
    # which is required for client-side routing to work correctly.
    if _WEB_DIST.is_dir():
        app.mount("/", StaticFiles(directory=str(_WEB_DIST), html=True), name="static")
    else:
        logger.warning(
            "web/dist not found at %s — dashboard will not be served. "
            "Run scripts/deploy.sh to build it.",
            _WEB_DIST,
            extra={"event": "web_dist_missing"},
        )

    return app


app = create_app()


if __name__ == "__main__":
    cfg = _load_api_config()
    server_cfg = cfg.get("server", {})
    uvicorn.run(
        "main:app",
        host=server_cfg.get("host", "0.0.0.0"),
        port=server_cfg.get("port", 8000),
        reload=False,
    )
