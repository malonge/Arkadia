"""GET /version — deployment metadata."""

from __future__ import annotations

import subprocess

from fastapi import APIRouter
from fastapi.responses import JSONResponse

router = APIRouter()

_VERSION = "1.1.0"
_SERVICE = "home-monitor-api"


def _git_commit() -> str:
    """Return the current git commit short SHA, or 'unknown' on failure."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=3,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return "unknown"


@router.get("/version")
async def version() -> JSONResponse:
    """Return service name, version string, and git commit."""
    return JSONResponse(
        content={
            "service": _SERVICE,
            "version": _VERSION,
            "git_commit": _git_commit(),
        }
    )
