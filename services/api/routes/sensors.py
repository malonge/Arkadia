"""Sensor reading endpoints.

Routes:
    GET /sensors                     — all latest readings
    GET /sensors/{sensor_id}         — latest reading for one sensor
    GET /sensors/{sensor_id}/status  — staleness metadata
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

router = APIRouter()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@router.get("/sensors")
async def list_sensors(request: Request) -> JSONResponse:
    """Return the latest reading from every sensor in the store."""
    store = request.app.state.store
    entries = store.all()
    return JSONResponse(
        content={
            sensor_id: entry.payload for sensor_id, entry in entries.items()
        }
    )


@router.get("/sensors/{sensor_id}")
async def get_sensor(sensor_id: str, request: Request) -> JSONResponse:
    """Return the latest reading for *sensor_id*.

    Responses:
        200  Reading available.
        404  Unknown sensor ID (not in known_sensor_ids config).
        503  Known sensor but no data received yet.
    """
    known_ids: set[str] = request.app.state.known_sensor_ids
    store = request.app.state.store

    if sensor_id not in known_ids:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Unknown sensor: {sensor_id!r}"},
        )

    entry = store.get(sensor_id)
    if entry is None:
        return JSONResponse(
            status_code=503,
            content={"detail": f"No data received yet for sensor: {sensor_id!r}"},
        )

    return JSONResponse(content=entry.payload)


@router.get("/sensors/{sensor_id}/status")
async def get_sensor_status(sensor_id: str, request: Request) -> JSONResponse:
    """Return freshness and staleness information for *sensor_id*.

    Responses:
        200  Status returned (even when stale).
        404  Unknown sensor ID.
        503  Known sensor but no data received yet.
    """
    known_ids: set[str] = request.app.state.known_sensor_ids
    store = request.app.state.store
    stale_threshold: int = request.app.state.stale_threshold_seconds

    if sensor_id not in known_ids:
        return JSONResponse(
            status_code=404,
            content={"detail": f"Unknown sensor: {sensor_id!r}"},
        )

    entry = store.get(sensor_id)
    if entry is None:
        return JSONResponse(
            status_code=503,
            content={"detail": f"No data received yet for sensor: {sensor_id!r}"},
        )

    now = _utcnow()
    seconds_since = (now - entry.received_at).total_seconds()
    stale = seconds_since > stale_threshold

    connectivity_store = request.app.state.connectivity
    connectivity = connectivity_store.get(sensor_id)

    return JSONResponse(
        content={
            "sensor_id": sensor_id,
            "last_seen": entry.received_at.isoformat(),
            "seconds_since_update": round(seconds_since, 1),
            "stale": stale,
            "stale_threshold_seconds": stale_threshold,
            "connectivity": connectivity,
        }
    )
