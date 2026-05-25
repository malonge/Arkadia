"""Thread-safe in-memory sensor state store."""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


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
