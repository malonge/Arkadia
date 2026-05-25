"""Thread-safe in-memory sensor state store."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Literal

ConnectivityStatus = Literal["online", "offline", "unknown"]


@dataclass
class StoreEntry:
    """A single sensor's latest reading plus receipt metadata."""

    payload: dict[str, Any]
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class SensorStore:
    """Thread-safe dict of the latest payload for each sensor.

    Keyed by ``sensor_id``.  Only summary payloads (retained topics) are
    stored here; ``AudioStreamPayload`` frames bypass the store and are
    forwarded directly to the WebSocket broadcaster.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, StoreEntry] = {}

    def upsert(self, sensor_id: str, payload: dict[str, Any]) -> None:
        """Insert or replace the entry for *sensor_id*."""
        with self._lock:
            self._data[sensor_id] = StoreEntry(
                payload=payload,
                received_at=datetime.now(timezone.utc),
            )

    def get(self, sensor_id: str) -> StoreEntry | None:
        """Return the entry for *sensor_id*, or ``None`` if absent."""
        with self._lock:
            return self._data.get(sensor_id)

    def all(self) -> dict[str, StoreEntry]:
        """Return a shallow copy of the entire store."""
        with self._lock:
            return dict(self._data)

    def __len__(self) -> int:
        with self._lock:
            return len(self._data)


class ConnectivityStore:
    """Thread-safe map of sensor_id → connectivity status.

    Updated by messages arriving on ``home/status/#``.

    Status values:
        ``"online"``   — the sensor service published a successful startup.
        ``"offline"``  — the broker delivered the service's LWT (ungraceful exit)
                         or the service explicitly published offline before stopping.
        ``"unknown"``  — no status message has been received yet.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._data: dict[str, ConnectivityStatus] = {}

    def update(self, sensor_id: str, status: ConnectivityStatus) -> None:
        """Record *status* for *sensor_id*."""
        with self._lock:
            self._data[sensor_id] = status

    def get(self, sensor_id: str) -> ConnectivityStatus:
        """Return the current status for *sensor_id*, defaulting to ``"unknown"``."""
        with self._lock:
            return self._data.get(sensor_id, "unknown")

    def all(self) -> dict[str, ConnectivityStatus]:
        """Return a shallow copy of all known statuses."""
        with self._lock:
            return dict(self._data)
