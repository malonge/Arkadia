"""paho-mqtt wrapper with auto-reconnect and structured logging."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Structured JSON logging formatter
# ---------------------------------------------------------------------------


class JsonFormatter(logging.Formatter):
    """Emit log records as single-line JSON objects with UTC timestamps."""

    def formatTime(self, record: logging.LogRecord, datefmt: str | None = None) -> str:
        """Return the log record creation time as a UTC ISO 8601 string.

        Overrides the default implementation, which uses ``time.localtime``
        (the process's local timezone).  The ``Z`` suffix in ISO 8601 denotes
        UTC; using localtime would produce a misleading timestamp on any host
        not configured to UTC.
        """
        dt = datetime.fromtimestamp(record.created, tz=timezone.utc)
        if datefmt:
            return dt.strftime(datefmt)
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record),
            "level": record.levelname,
            "service": record.name,
            "event": getattr(record, "event", "log"),
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload)


def configure_logging(level: str = "INFO", fmt: str = "json") -> None:
    """Configure the root logger with structured JSON or plain-text output.

    Explicitly replaces all existing handlers on the root logger so that this
    function is not a no-op when called after :func:`logging.basicConfig` (or
    any other logging setup) has already installed handlers.
    """
    handler = logging.StreamHandler()
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())


# ---------------------------------------------------------------------------
# LWT configuration
# ---------------------------------------------------------------------------


class LWTConfig:
    """Last Will and Testament configuration."""

    def __init__(self, topic: str, payload: str, qos: int = 1, retain: bool = True) -> None:
        self.topic = topic
        self.payload = payload
        self.qos = qos
        self.retain = retain


# ---------------------------------------------------------------------------
# MQTTClient
# ---------------------------------------------------------------------------


class MQTTClient:
    """Thin paho-mqtt wrapper with auto-reconnect and structured logging.

    Usage::

        client = MQTTClient(client_id="my-service", broker_host="localhost")
        client.connect()
        client.loop_start()
        client.publish("home/sensors/climate/bme280", payload_json, qos=1, retain=True)
    """

    def __init__(
        self,
        client_id: str,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        keepalive: int = 60,
        lwt: LWTConfig | None = None,
        reconnect_delay: float = 5.0,
    ) -> None:
        self._broker_host = broker_host
        self._broker_port = broker_port
        self._keepalive = keepalive
        self._lwt = lwt
        self._reconnect_delay = reconnect_delay
        self._connected = False

        self._client = mqtt.Client(
            client_id=client_id,
            callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
        )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message

        self._message_callbacks: dict[str, tuple[Callable[[str, bytes], None], int]] = {}

        if lwt:
            self._client.will_set(
                lwt.topic,
                payload=lwt.payload,
                qos=lwt.qos,
                retain=lwt.retain,
            )

    # ------------------------------------------------------------------
    # paho callbacks
    # ------------------------------------------------------------------

    def _on_connect(
        self,
        client: mqtt.Client,
        userdata: Any,
        connect_flags: mqtt.ConnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: Any,
    ) -> None:
        if reason_code.is_failure:
            logger.error(
                "MQTT connection failed: %s",
                reason_code,
                extra={"event": "mqtt_connect_failed"},
            )
            return
        self._connected = True
        logger.info("Connected to broker", extra={"event": "mqtt_connected"})
        for topic, (_, qos) in self._message_callbacks.items():
            self._client.subscribe(topic, qos=qos)

    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata: Any,
        disconnect_flags: mqtt.DisconnectFlags,
        reason_code: mqtt.ReasonCode,
        properties: Any,
    ) -> None:
        self._connected = False
        if reason_code.is_failure:
            logger.warning(
                "Unexpected disconnect (rc=%s); will reconnect in %ss",
                reason_code,
                self._reconnect_delay,
                extra={"event": "mqtt_disconnected"},
            )
        else:
            logger.info("Disconnected from broker", extra={"event": "mqtt_disconnected"})

    def _on_message(
        self,
        client: mqtt.Client,
        userdata: Any,
        message: mqtt.MQTTMessage,
    ) -> None:
        topic = message.topic
        for pattern, (cb, _) in self._message_callbacks.items():
            if mqtt.topic_matches_sub(pattern, topic):
                try:
                    cb(topic, message.payload)
                except Exception:
                    logger.exception(
                        "Error in message callback for topic %s",
                        topic,
                        extra={"event": "mqtt_callback_error"},
                    )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def connect(self) -> None:
        """Initiate a connection to the broker.

        Opens the TCP socket and sends the MQTT ``CONNECT`` packet, then
        returns immediately.  The ``CONNACK`` response is processed
        asynchronously; ``is_connected`` will be ``False`` until
        ``loop_start()`` is running and the broker acknowledges the
        connection.
        """
        logger.info(
            "Connecting to %s:%s",
            self._broker_host,
            self._broker_port,
            extra={"event": "mqtt_connecting"},
        )
        self._client.reconnect_delay_set(
            min_delay=1,
            max_delay=int(self._reconnect_delay),
        )
        self._client.connect(
            self._broker_host,
            self._broker_port,
            self._keepalive,
        )

    def loop_start(self) -> None:
        """Start the paho network loop in a background thread."""
        self._client.loop_start()

    def loop_stop(self) -> None:
        """Stop the background network loop."""
        self._client.loop_stop()

    def disconnect(self) -> None:
        """Gracefully disconnect from the broker."""
        self._client.disconnect()

    def publish(
        self,
        topic: str,
        payload: str | bytes,
        qos: int = 1,
        retain: bool = False,
    ) -> None:
        """Publish a message to *topic*.

        Raises ``RuntimeError`` if the client is not currently connected to
        the broker.  Callers should call ``connect()`` and ``loop_start()``
        before publishing.
        """
        if not self._connected:
            raise RuntimeError("Cannot publish: not connected to broker")
        result = self._client.publish(topic, payload=payload, qos=qos, retain=retain)
        result.wait_for_publish(timeout=5)
        logger.debug(
            "Published to %s",
            topic,
            extra={"event": "mqtt_publish"},
        )

    def subscribe(
        self,
        topic: str,
        callback: Callable[[str, bytes], None],
        qos: int = 1,
    ) -> None:
        """Subscribe to *topic* and register *callback* for matching messages.

        The callback signature is ``(topic: str, payload: bytes) -> None``.
        Subscriptions made before ``connect()`` are re-applied on reconnect.
        """
        self._message_callbacks[topic] = (callback, qos)
        if self._connected:
            self._client.subscribe(topic, qos=qos)
        logger.debug("Subscribed to %s", topic, extra={"event": "mqtt_subscribe"})

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if the client is currently connected to the broker."""
        return self._connected
