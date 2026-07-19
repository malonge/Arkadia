"""SGP40 VOC sensor service.

Polling loop:
  1. Call sensor.read() every ~1 s so the Sensirion VOC Algorithm can
     maintain its internal baseline.
  2. Every publish_interval_seconds (default 60 s), publish the latest
     VOC Index to the configured MQTT topic.
  3. On SIGTERM/SIGINT, complete the current 1-second sample, publish a
     final reading if available, then shut down cleanly.
"""

from __future__ import annotations

import logging
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from common.config import load_config
from common.i2c import I2CError
from common.models import Diagnostics, Meta, SGP40Payload, SGP40Readings
from common.mqtt import LWTConfig, MQTTClient, configure_logging

sys.path.insert(0, str(Path(__file__).parent))

from sensor import SGP40Sensor, _SAMPLE_INTERVAL_S

logger = logging.getLogger("sgp40")

_stop = threading.Event()


def _handle_signal(signum: int, frame: object) -> None:
    logger.info(
        "Signal %d received — shutting down", signum, extra={"event": "service_shutdown"}
    )
    _stop.set()


def _wait_for_connect(client: MQTTClient, timeout: float = 15.0) -> bool:
    deadline = time.monotonic() + timeout
    while not client.is_connected:
        if time.monotonic() >= deadline:
            return False
        if _stop.is_set():
            return False
        _stop.wait(timeout=0.1)
    return True


def main() -> None:
    configure_logging(level="INFO", fmt="text")

    config_path = Path(__file__).parent / "config.toml"
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        logger.critical("Failed to load config from %s: %s", config_path, exc)
        sys.exit(1)

    configure_logging(
        level=cfg["logging"]["level"],
        fmt=cfg["logging"]["format"],
    )

    logger.info("SGP40 service starting", extra={"event": "service_started"})
    logger.info("Config loaded from %s", config_path, extra={"event": "config_loaded"})

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    broker = cfg["broker"]
    mqtt_cfg = cfg["mqtt"]

    status_topic = "home/status/sgp40"
    client = MQTTClient(
        client_id=mqtt_cfg["client_id"],
        broker_host=broker["host"],
        broker_port=broker["port"],
        keepalive=broker["keepalive"],
        lwt=LWTConfig(
            topic=status_topic,
            payload='{"status": "offline"}',
            qos=1,
            retain=True,
        ),
    )

    try:
        client.connect()
    except Exception as exc:
        logger.critical(
            "Cannot reach MQTT broker at %s:%d: %s",
            broker["host"],
            broker["port"],
            exc,
        )
        sys.exit(1)

    client.loop_start()

    if not _wait_for_connect(client):
        logger.critical(
            "Timed out waiting for MQTT connection to %s:%d",
            broker["host"],
            broker["port"],
        )
        client.loop_stop()
        sys.exit(1)

    sensor_cfg = cfg["sensor"]
    sensor = SGP40Sensor(
        bus=sensor_cfg.get("i2c_bus", 1),
        address=sensor_cfg.get("i2c_address", 0x59),
    )

    try:
        sensor.open()
    except I2CError as exc:
        logger.critical("Sensor init failed: %s", exc, extra={"event": "sensor_error"})
        client.loop_stop()
        sys.exit(1)

    try:
        client.publish(status_topic, '{"status": "online"}', qos=1, retain=True)
        logger.info("Published online status", extra={"event": "status_online"})
    except RuntimeError as exc:
        logger.warning("Could not publish online status: %s", exc)

    topic: str = mqtt_cfg["topic"]
    qos: int = mqtt_cfg.get("qos", 1)
    retain: bool = mqtt_cfg.get("retain", True)
    publish_interval: float = float(sensor_cfg.get("publish_interval_seconds", 60))

    service_start = time.monotonic()
    read_failures = 0
    last_voc_index: int | None = None

    logger.info(
        "Entering poll loop (sample_interval=%.0fs, publish_interval=%.0fs)",
        _SAMPLE_INTERVAL_S,
        publish_interval,
        extra={"event": "poll_loop_start"},
    )

    next_publish = time.monotonic() + publish_interval

    while not _stop.is_set():
        # ---- 1-second sample ------------------------------------------------
        cycle_start = time.monotonic()
        try:
            data = sensor.read()
            last_voc_index = data["voc_index"]
            logger.debug(
                "VOC Index: %d",
                last_voc_index,
                extra={"event": "sensor_read"},
            )
        except I2CError as exc:
            read_failures += 1
            logger.warning(
                "Read failed: %s (total failures: %d)",
                exc,
                read_failures,
                extra={"event": "sensor_error"},
            )

        # ---- Publish on interval --------------------------------------------
        now = time.monotonic()
        if now >= next_publish and last_voc_index is not None:
            logger.info(
                "VOC Index: %d (failures: %d)",
                last_voc_index,
                read_failures,
                extra={"event": "sensor_read"},
            )
            payload = SGP40Payload(
                sensor_id="sgp40",
                timestamp=datetime.now(tz=timezone.utc),
                readings=SGP40Readings(voc_index=last_voc_index),
                meta=Meta(sample_count=1, aggregation="latest"),
                diagnostics=Diagnostics(
                    uptime_seconds=now - service_start,
                    read_failures=read_failures,
                ),
            )
            try:
                client.publish(topic, payload.model_dump_json(), qos=qos, retain=retain)
            except RuntimeError as exc:
                logger.error(
                    "Publish failed: %s", exc, extra={"event": "mqtt_publish_error"}
                )
            next_publish = now + publish_interval

        # ---- Sleep for the remainder of the 1-second sample interval --------
        elapsed = time.monotonic() - cycle_start
        remaining = _SAMPLE_INTERVAL_S - elapsed
        if remaining > 0:
            _stop.wait(timeout=remaining)

    logger.info("Stopping poll loop", extra={"event": "service_shutdown"})
    sensor.close()
    client.loop_stop()
    client.disconnect()
    logger.info("SGP40 service stopped", extra={"event": "service_stopped"})


if __name__ == "__main__":
    main()
