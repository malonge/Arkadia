"""BME280 climate sensor service.

Polling loop:
  1. Collect sample_count raw readings with sample_interval_seconds between them.
  2. Compute median of each measurement across successful samples.
  3. Build a BME280Payload using common/models.py.
  4. Publish retained JSON to the configured MQTT topic.
  5. Sleep for the remainder of the interval, waking immediately on SIGTERM.
"""

from __future__ import annotations

import logging
import signal
import statistics
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from common.config import load_config
from common.i2c import I2CError
from common.models import BME280Payload, BME280Readings, Diagnostics, Meta
from common.mqtt import LWTConfig, MQTTClient, configure_logging

# Ensure sensor.py is importable regardless of the working directory.
# When running under systemd, WorkingDirectory is not set (to avoid
# requiring it to expand env vars), so we add the service directory
# to sys.path explicitly using __file__ which is always absolute.
sys.path.insert(0, str(Path(__file__).parent))

from sensor import BME280Sensor

logger = logging.getLogger("bme280")

# Used by the signal handler to interrupt the inter-cycle sleep cleanly.
_stop = threading.Event()


def _handle_signal(signum: int, frame: object) -> None:
    logger.info(
        "Signal %d received — shutting down", signum, extra={"event": "service_shutdown"}
    )
    _stop.set()


def _wait_for_connect(client: MQTTClient, timeout: float = 15.0) -> bool:
    """Block until the client is connected or *timeout* seconds elapse.

    Uses ``_stop.wait`` so that a shutdown signal interrupts the wait
    immediately rather than after the next 0.1 s tick.
    """
    deadline = time.monotonic() + timeout
    while not client.is_connected:
        if time.monotonic() >= deadline:
            return False
        if _stop.is_set():
            return False
        _stop.wait(timeout=0.1)
    return True


def main() -> None:
    # ----------------------------------------------------------------
    # Logging bootstrap (plain text until config is loaded)
    # ----------------------------------------------------------------
    # Use configure_logging (not logging.basicConfig) so the call after
    # config is loaded actually replaces the handler with the JSON formatter
    # rather than being silently ignored.
    configure_logging(level="INFO", fmt="text")

    # ----------------------------------------------------------------
    # Configuration
    # ----------------------------------------------------------------
    config_path = Path(__file__).parent / "config.toml"
    try:
        cfg = load_config(config_path)
    except Exception as exc:
        logger.critical("Failed to load config from %s: %s", config_path, exc)
        sys.exit(1)

    # Reconfigure logging with settings from the merged config.
    configure_logging(
        level=cfg["logging"]["level"],
        fmt=cfg["logging"]["format"],
    )

    logger.info(
        "BME280 service starting", extra={"event": "service_started"}
    )
    logger.info(
        "Config loaded from %s", config_path, extra={"event": "config_loaded"}
    )

    # ----------------------------------------------------------------
    # Signal handling
    # ----------------------------------------------------------------
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    # ----------------------------------------------------------------
    # MQTT
    # ----------------------------------------------------------------
    broker = cfg["broker"]
    mqtt_cfg = cfg["mqtt"]

    status_topic = "home/status/bme280"
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

    # ----------------------------------------------------------------
    # Hardware
    # ----------------------------------------------------------------
    sensor_cfg = cfg["sensor"]
    sensor = BME280Sensor(
        bus=sensor_cfg.get("i2c_bus", 1),
        address=sensor_cfg["i2c_address"],
    )

    try:
        sensor.open()
    except I2CError as exc:
        logger.critical("Sensor init failed: %s", exc, extra={"event": "sensor_error"})
        client.loop_stop()
        sys.exit(1)

    # Announce successful startup so subscribers know this sensor is live.
    try:
        client.publish(status_topic, '{"status": "online"}', qos=1, retain=True)
        logger.info("Published online status", extra={"event": "status_online"})
    except RuntimeError as exc:
        logger.warning("Could not publish online status: %s", exc)

    # ----------------------------------------------------------------
    # Poll loop
    # ----------------------------------------------------------------
    sample_count: int = sensor_cfg.get("sample_count", 5)
    sample_interval: float = sensor_cfg.get("sample_interval_seconds", 0.5)
    interval: float = sensor_cfg.get("interval_seconds", 30)
    topic: str = mqtt_cfg["topic"]
    qos: int = mqtt_cfg.get("qos", 1)
    retain: bool = mqtt_cfg.get("retain", True)

    service_start = time.monotonic()
    read_failures = 0

    logger.info(
        "Entering poll loop (interval=%.0fs, samples=%d)",
        interval,
        sample_count,
        extra={"event": "poll_loop_start"},
    )

    while not _stop.is_set():
        cycle_start = time.monotonic()

        # Collect samples
        samples: list[dict[str, float]] = []
        for i in range(sample_count):
            try:
                samples.append(sensor.read())
                logger.debug(
                    "Sample %d/%d: %.2f°C %.1f%% %.1fhPa",
                    i + 1,
                    sample_count,
                    samples[-1]["temperature_c"],
                    samples[-1]["humidity_pct"],
                    samples[-1]["pressure_hpa"],
                    extra={"event": "sensor_read"},
                )
            except I2CError as exc:
                read_failures += 1
                logger.warning(
                    "Sample %d/%d failed: %s", i + 1, sample_count, exc,
                    extra={"event": "sensor_error"},
                )
            if i < sample_count - 1:
                _stop.wait(timeout=sample_interval)
                if _stop.is_set():
                    break

        if not samples:
            logger.error(
                "All %d samples failed; skipping cycle", sample_count,
                extra={"event": "sensor_error"},
            )
            _stop.wait(timeout=interval)
            continue

        # Compute medians
        temperature_c = statistics.median(s["temperature_c"] for s in samples)
        humidity_pct = statistics.median(s["humidity_pct"] for s in samples)
        pressure_hpa = statistics.median(s["pressure_hpa"] for s in samples)

        logger.info(
            "Reading: %.2f°C  %.1f%%  %.1f hPa  (%d/%d samples)",
            temperature_c,
            humidity_pct,
            pressure_hpa,
            len(samples),
            sample_count,
            extra={"event": "sensor_read"},
        )

        # Build and publish payload
        payload = BME280Payload(
            sensor_id="bme280",
            timestamp=datetime.now(tz=timezone.utc),
            readings=BME280Readings(
                temperature_c=temperature_c,
                humidity_pct=humidity_pct,
                pressure_hpa=pressure_hpa,
            ),
            meta=Meta(sample_count=len(samples), aggregation="median"),
            diagnostics=Diagnostics(
                uptime_seconds=time.monotonic() - service_start,
                read_failures=read_failures,
            ),
        )

        try:
            client.publish(topic, payload.model_dump_json(), qos=qos, retain=retain)
        except RuntimeError as exc:
            logger.error(
                "Publish failed: %s", exc, extra={"event": "mqtt_publish_error"}
            )

        # Sleep for the remainder of the cycle interval.
        elapsed = time.monotonic() - cycle_start
        remaining = interval - elapsed
        if remaining > 0:
            _stop.wait(timeout=remaining)

    # ----------------------------------------------------------------
    # Shutdown
    # ----------------------------------------------------------------
    logger.info("Stopping poll loop", extra={"event": "service_shutdown"})
    sensor.close()
    client.loop_stop()
    client.disconnect()
    logger.info("BME280 service stopped", extra={"event": "service_stopped"})


if __name__ == "__main__":
    main()
