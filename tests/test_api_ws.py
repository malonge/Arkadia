"""Unit tests for services/api/ws.py — AudioStreamBroadcaster."""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock

from services.api.ws import AudioStreamBroadcaster


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_broadcaster_with_loop() -> tuple[AudioStreamBroadcaster, asyncio.AbstractEventLoop]:
    loop = asyncio.new_event_loop()
    b = AudioStreamBroadcaster()
    b.set_loop(loop)
    return b, loop


def _run_loop_briefly(loop: asyncio.AbstractEventLoop, duration: float = 0.05) -> None:
    loop.run_until_complete(asyncio.sleep(duration))


# ---------------------------------------------------------------------------
# add / remove
# ---------------------------------------------------------------------------


class TestConnectionManagement:
    def test_add_increments_count(self):
        b = AudioStreamBroadcaster()
        ws = MagicMock()
        b.add(ws)
        assert b.connection_count == 1

    def test_remove_decrements_count(self):
        b = AudioStreamBroadcaster()
        ws = MagicMock()
        b.add(ws)
        b.remove(ws)
        assert b.connection_count == 0

    def test_remove_unknown_is_noop(self):
        b = AudioStreamBroadcaster()
        b.remove(MagicMock())
        assert b.connection_count == 0

    def test_add_multiple(self):
        b = AudioStreamBroadcaster()
        for _ in range(5):
            b.add(MagicMock())
        assert b.connection_count == 5


# ---------------------------------------------------------------------------
# broadcast
# ---------------------------------------------------------------------------


class TestBroadcast:
    def test_broadcast_no_loop_is_noop(self):
        b = AudioStreamBroadcaster()
        ws = MagicMock()
        b.add(ws)
        # Should not raise
        b.broadcast('{"test": true}')

    def test_broadcast_no_connections_is_noop(self):
        loop = asyncio.new_event_loop()
        b = AudioStreamBroadcaster()
        b.set_loop(loop)
        # Should not raise and should not schedule anything
        b.broadcast('{"test": true}')
        loop.close()

    def test_broadcast_sends_to_all_connections(self):
        loop = asyncio.new_event_loop()
        b = AudioStreamBroadcaster()
        b.set_loop(loop)

        sent: list[tuple[object, str]] = []

        async def mock_send_text(data: str) -> None:
            sent.append(data)

        ws1 = MagicMock()
        ws1.send_text = mock_send_text
        ws2 = MagicMock()
        ws2.send_text = mock_send_text

        b.add(ws1)
        b.add(ws2)
        b.broadcast('{"frame": 1}')

        _run_loop_briefly(loop)
        loop.close()

        assert sent.count('{"frame": 1}') == 2

    def test_broadcast_removes_dead_connection(self):
        loop = asyncio.new_event_loop()
        b = AudioStreamBroadcaster()
        b.set_loop(loop)

        async def failing_send(data: str) -> None:
            raise ConnectionResetError("gone")

        ws_dead = MagicMock()
        ws_dead.send_text = failing_send

        async def ok_send(data: str) -> None:
            pass

        ws_ok = MagicMock()
        ws_ok.send_text = ok_send

        b.add(ws_dead)
        b.add(ws_ok)

        b.broadcast('{"frame": 1}')
        _run_loop_briefly(loop)
        loop.close()

        # Dead connection should be pruned
        assert b.connection_count == 1
        assert ws_dead not in b._connections
        assert ws_ok in b._connections

    def test_broadcast_from_different_thread(self):
        loop = asyncio.new_event_loop()
        b = AudioStreamBroadcaster()
        b.set_loop(loop)

        received: list[str] = []

        async def mock_send(data: str) -> None:
            received.append(data)

        ws = MagicMock()
        ws.send_text = mock_send
        b.add(ws)

        def thread_func() -> None:
            b.broadcast('{"from": "thread"}')

        t = threading.Thread(target=thread_func)
        t.start()
        t.join()

        _run_loop_briefly(loop)
        loop.close()

        assert received == ['{"from": "thread"}']
