"""Unit tests for common/mqtt.py — no broker required."""

import json
import logging
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, call

import pytest

from common.mqtt import JsonFormatter, MQTTClient


# ---------------------------------------------------------------------------
# Bug 1: _message_callbacks must store (callback, qos) and replay QoS on reconnect
# ---------------------------------------------------------------------------


class TestSubscribeStoresQoS:
    def _make_client(self) -> MQTTClient:
        return MQTTClient(client_id="test-client", broker_host="localhost")

    def test_default_qos_stored(self):
        client = self._make_client()
        cb = lambda topic, payload: None
        client.subscribe("home/sensors/#", cb)
        stored_cb, stored_qos = client._message_callbacks["home/sensors/#"]
        assert stored_cb is cb
        assert stored_qos == 1  # the wrapper's default

    def test_explicit_qos_stored(self):
        client = self._make_client()
        cb = lambda topic, payload: None
        client.subscribe("home/sensors/#", cb, qos=2)
        _, stored_qos = client._message_callbacks["home/sensors/#"]
        assert stored_qos == 2

    def test_qos_zero_stored(self):
        client = self._make_client()
        cb = lambda topic, payload: None
        client.subscribe("home/sensors/#", cb, qos=0)
        _, stored_qos = client._message_callbacks["home/sensors/#"]
        assert stored_qos == 0

    def test_reconnect_resubscribes_with_original_qos(self):
        """_on_connect must forward the stored QoS, not default to QoS 0."""
        client = self._make_client()
        cb = lambda topic, payload: None
        client.subscribe("home/sensors/#", cb, qos=2)

        mock_paho = MagicMock()
        client._client = mock_paho

        mock_reason = MagicMock()
        mock_reason.is_failure = False
        client._on_connect(mock_paho, None, MagicMock(), mock_reason, None)

        mock_paho.subscribe.assert_called_once_with("home/sensors/#", qos=2)

    def test_reconnect_preserves_qos_for_multiple_subscriptions(self):
        client = self._make_client()
        cb1 = lambda t, p: None
        cb2 = lambda t, p: None
        client.subscribe("topic/a", cb1, qos=1)
        client.subscribe("topic/b", cb2, qos=0)

        mock_paho = MagicMock()
        client._client = mock_paho

        mock_reason = MagicMock()
        mock_reason.is_failure = False
        client._on_connect(mock_paho, None, MagicMock(), mock_reason, None)

        calls = mock_paho.subscribe.call_args_list
        assert call("topic/a", qos=1) in calls
        assert call("topic/b", qos=0) in calls

    def test_failed_reconnect_does_not_resubscribe(self):
        """A failed connection attempt must not trigger re-subscription."""
        client = self._make_client()
        cb = lambda t, p: None
        client.subscribe("home/#", cb, qos=1)

        mock_paho = MagicMock()
        client._client = mock_paho

        mock_reason = MagicMock()
        mock_reason.is_failure = True
        client._on_connect(mock_paho, None, MagicMock(), mock_reason, None)

        mock_paho.subscribe.assert_not_called()

    def test_message_callback_invoked_correctly(self):
        """_on_message must still dispatch to the callback after the tuple refactor."""
        client = self._make_client()
        received = []
        client.subscribe("home/sensors/#", lambda t, p: received.append((t, p)), qos=1)

        mock_msg = MagicMock()
        mock_msg.topic = "home/sensors/climate/bme280"
        mock_msg.payload = b'{"sensor_id": "bme280"}'
        client._on_message(MagicMock(), None, mock_msg)

        assert len(received) == 1
        assert received[0][0] == "home/sensors/climate/bme280"


# ---------------------------------------------------------------------------
# Bug 4: JsonFormatter.formatTime must produce UTC timestamps
# ---------------------------------------------------------------------------


class TestJsonFormatterUTC:
    def _make_record(self, *, epoch: float | None = None) -> logging.LogRecord:
        record = logging.LogRecord(
            name="test.service",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        if epoch is not None:
            record.created = epoch
        return record

    def test_formattime_returns_utc(self):
        """formatTime must return UTC, not local time."""
        # Use a known epoch: 2026-05-08 12:00:00 UTC == 1746705600
        known_epoch = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        record = self._make_record(epoch=known_epoch)
        fmt = JsonFormatter()
        result = fmt.formatTime(record)
        assert result == "2026-05-08T12:00:00Z"

    def test_formattime_ends_with_z(self):
        record = self._make_record()
        fmt = JsonFormatter()
        result = fmt.formatTime(record)
        assert result.endswith("Z"), f"Expected Z suffix, got: {result!r}"

    def test_formattime_custom_datefmt(self):
        known_epoch = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        record = self._make_record(epoch=known_epoch)
        fmt = JsonFormatter()
        result = fmt.formatTime(record, datefmt="%Y/%m/%d %H:%M")
        assert result == "2026/05/08 12:00"

    def test_format_includes_utc_timestamp(self):
        """The full format() output must have a correct UTC timestamp field."""
        known_epoch = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        record = self._make_record(epoch=known_epoch)
        record.extra_event = "test_event"

        fmt = JsonFormatter()
        output = json.loads(fmt.format(record))
        assert output["timestamp"] == "2026-05-08T12:00:00Z"

    def test_formattime_independent_of_local_timezone(self):
        """Patching time.localtime to a non-UTC zone must not affect output."""
        known_epoch = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc).timestamp()
        record = self._make_record(epoch=known_epoch)

        fmt = JsonFormatter()
        # Simulate a system configured to UTC+5 by patching time.localtime
        with patch("time.localtime", return_value=time.gmtime(known_epoch + 5 * 3600)):
            result = fmt.formatTime(record)

        # Must still return the real UTC time, not UTC+5
        assert result == "2026-05-08T12:00:00Z"
