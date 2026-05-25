"""GET /health — broker connectivity and uptime."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

if TYPE_CHECKING:
    pass

router = APIRouter()

_start_time = time.monotonic()


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    """Return broker connectivity status and service uptime."""
    mqtt_client = request.app.state.mqtt_client
    uptime = round(time.monotonic() - _start_time, 1)
    broker_ok = mqtt_client.is_connected if mqtt_client is not None else False
    status = "ok" if broker_ok else "degraded"
    return JSONResponse(
        content={
            "status": status,
            "broker_connected": broker_ok,
            "uptime_seconds": uptime,
        }
    )
