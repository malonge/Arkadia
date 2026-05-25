"""WebSocket broadcaster for real-time audio stream frames."""

from __future__ import annotations

import asyncio
import logging
import threading
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from fastapi import WebSocket

logger = logging.getLogger(__name__)


class AudioStreamBroadcaster:
    """Holds active WebSocket connections and forwards audio stream frames.

    MQTT callbacks fire in paho's background thread.  To send data to
    FastAPI WebSocket clients (which live on the asyncio event loop) we
    schedule coroutines via :func:`asyncio.run_coroutine_threadsafe` using
    the loop captured at startup.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._connections: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Capture the running asyncio event loop for cross-thread dispatch."""
        self._loop = loop

    def add(self, ws: WebSocket) -> None:
        """Register a new WebSocket connection."""
        with self._lock:
            self._connections.add(ws)
        logger.debug(
            "WebSocket client added (%d active)",
            len(self._connections),
            extra={"event": "ws_client_added"},
        )

    def remove(self, ws: WebSocket) -> None:
        """Deregister a WebSocket connection."""
        with self._lock:
            self._connections.discard(ws)
        logger.debug(
            "WebSocket client removed (%d active)",
            len(self._connections),
            extra={"event": "ws_client_removed"},
        )

    @property
    def connection_count(self) -> int:
        """Number of currently active WebSocket connections."""
        with self._lock:
            return len(self._connections)

    def broadcast(self, data: str) -> None:
        """Send *data* to all connected clients from any thread.

        Clients that have disconnected or raised an error are silently
        removed.  This method is non-blocking: it schedules the async
        work on the event loop and returns immediately.
        """
        if self._loop is None or not self._connections:
            return

        with self._lock:
            connections = set(self._connections)

        async def _send_all() -> None:
            dead: set[WebSocket] = set()
            for ws in connections:
                try:
                    await ws.send_text(data)
                except Exception:
                    dead.add(ws)
            if dead:
                with self._lock:
                    self._connections -= dead
                logger.debug(
                    "Removed %d dead WebSocket connection(s)",
                    len(dead),
                    extra={"event": "ws_client_dropped"},
                )

        asyncio.run_coroutine_threadsafe(_send_all(), self._loop)
