"""Unit tests for common/mqtt.py — no broker required."""

import json
import logging
import sys
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
        def cb(topic, payload): pass
        client = self._make_client()
        client.subscribe("home/sensors/#", cb)
        stored_cb, stored_qos = client._message_callbacks["home/sensors/#"]
        assert stored_cb is cb
        assert stored_qos == 1  # the wrapper's default

    def test_explicit_qos_stored(self):
        def cb(topic, payload): pass
        client = self._make_client()
        client.subscribe("home/sensors/#", cb, qos=2)
        _, stored_qos = client._message_callbacks["home/sensors/#"]
        assert stored_qos == 2

    def test_qos_zero_stored(self):
        def cb(topic, payload): pass
        client = self._make_client()
        client.subscribe("home/sensors/#", cb, qos=0)
        _, stored_qos = client._message_callbacks["home/sensors/#"]
        assert stored_qos == 0

    def test_reconnect_resubscribes_with_original_qos(self):
        """_on_connect must forward the stored QoS, not default to QoS 0."""
        def cb(topic, payload): pass
        client = self._make_client()
        client.subscribe("home/sensors/#", cb, qos=2)

        mock_paho = MagicMock()
        client._client = mock_paho

        mock_reason = MagicMock()
        mock_reason.is_failure = False
        client._on_connect(mock_paho, None, MagicMock(), mock_reason, None)

        mock_paho.subscribe.assert_called_once_with("home/sensors/#", qos=2)

    def test_reconnect_preserves_qos_for_multiple_subscriptions(self):
        def cb1(t, p): pass
        def cb2(t, p): pass
        client = self._make_client()
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
        def cb(t, p): pass
        client = self._make_client()
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
        def collect(t, p): received.append((t, p))
        client.subscribe("home/sensors/#", collect, qos=1)

        mock_msg = MagicMock()
        mock_msg.topic = "home/sensors/climate/bme280"
        mock_msg.payload = b'{"sensor_id": "bme280"}'
        client._on_message(MagicMock(), None, mock_msg)

        assert len(received) == 1
        assert received[0][0] == "home/sensors/climate/bme280"


# ---------------------------------------------------------------------------
# configure_logging replaces existing handlers (not a basicConfig no-op)
# ---------------------------------------------------------------------------


class TestConfigureLogging:
    def setup_method(self):
        # Capture root logger state before each test
        self._original_handlers = logging.root.handlers[:]
        self._original_level = logging.root.level

    def teardown_method(self):
        # Restore root logger so other tests are unaffected
        logging.root.handlers.clear()
        for h in self._original_handlers:
            logging.root.addHandler(h)
        logging.root.setLevel(self._original_level)

    def test_installs_json_formatter_even_after_basicconfig(self):
        """configure_logging must replace handlers, not skip due to basicConfig no-op."""
        import logging as _logging
        # Simulate what main.py's bootstrap used to do
        _logging.basicConfig(level=_logging.INFO, stream=sys.stderr)
        assert len(_logging.root.handlers) >= 1

        from common.mqtt import configure_logging, JsonFormatter
        configure_logging(level="INFO", fmt="json")

        assert len(_logging.root.handlers) == 1
        assert isinstance(_logging.root.handlers[0].formatter, JsonFormatter)

    def test_replaces_all_existing_handlers(self):
        import logging as _logging
        # Install two handlers first
        _logging.root.addHandler(_logging.StreamHandler())
        _logging.root.addHandler(_logging.StreamHandler())
        assert len(_logging.root.handlers) >= 2

        from common.mqtt import configure_logging
        configure_logging(level="DEBUG", fmt="json")

        assert len(_logging.root.handlers) == 1
        assert _logging.root.level == _logging.DEBUG

    def test_text_format_has_no_json_formatter(self):
        from common.mqtt import configure_logging, JsonFormatter
        configure_logging(level="INFO", fmt="text")
        assert not isinstance(logging.root.handlers[0].formatter, JsonFormatter)


# ---------------------------------------------------------------------------
# publish() raises RuntimeError when not connected
# ---------------------------------------------------------------------------


class TestPublishConnectedGuard:
    def test_publish_raises_when_disconnected(self):
        client = MQTTClient(client_id="test-client", broker_host="localhost")
        assert not client.is_connected
        with pytest.raises(RuntimeError, match="not connected"):
            client.publish("home/sensors/test", b"payload")

    def test_publish_allowed_when_connected(self):
        client = MQTTClient(client_id="test-client", broker_host="localhost")
        client._connected = True

        mock_result = MagicMock()
        mock_result.wait_for_publish = MagicMock()
        client._client = MagicMock()
        client._client.publish.return_value = mock_result

        client.publish("home/sensors/test", b"payload", qos=1, retain=True)
        client._client.publish.assert_called_once_with(
            "home/sensors/test", payload=b"payload", qos=1, retain=True
        )


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
