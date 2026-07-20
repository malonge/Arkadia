"""SCD40 CO₂ sensor service.

Polling loop:
  1. Collect sample_count readings, each gated by the SCD40's 5-second
     data_ready cycle (no explicit inter-sample sleep is needed).
  2. Compute median of co2_ppm, temperature_c, and humidity_pct.
  3. Build an SCD40Payload using common/models.py.
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
from common.models import Diagnostics, Meta, SCD40Payload, SCD40Readings
from common.mqtt import LWTConfig, MQTTClient, configure_logging

# Ensure sensor.py is importable regardless of the working directory.
sys.path.insert(0, str(Path(__file__).parent))

from sensor import SCD40Sensor

logger = logging.getLogger("scd40")

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
    # ----------------------------------------------------------------
    # Logging bootstrap
    # ----------------------------------------------------------------
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

    configure_logging(
        level=cfg["logging"]["level"],
        fmt=cfg["logging"]["format"],
    )

    logger.info("SCD40 service starting", extra={"event": "service_started"})
    logger.info("Config loaded from %s", config_path, extra={"event": "config_loaded"})

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

    status_topic = "home/status/scd40"
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
    sensor = SCD40Sensor(
        bus=sensor_cfg.get("i2c_bus", 1),
        address=sensor_cfg["i2c_address"],
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

    # ----------------------------------------------------------------
    # Poll loop
    # ----------------------------------------------------------------
    sample_count: int = sensor_cfg.get("sample_count", 3)
    interval: float = sensor_cfg.get("interval_seconds", 60)
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

        # Collect samples — each read() blocks up to ~5 s for data_ready.
        samples: list[dict[str, float]] = []
        for i in range(sample_count):
            if _stop.is_set():
                break
            try:
                sample = sensor.read()
                samples.append(sample)
                logger.debug(
                    "Sample %d/%d: %.0f ppm CO₂  %.2f°C  %.1f%%",
                    i + 1,
                    sample_count,
                    sample["co2_ppm"],
                    sample["temperature_c"],
                    sample["humidity_pct"],
                    extra={"event": "sensor_read"},
                )
            except I2CError as exc:
                read_failures += 1
                logger.warning(
                    "Sample %d/%d failed: %s", i + 1, sample_count, exc,
                    extra={"event": "sensor_error"},
                )

        if not samples:
            logger.error(
                "All %d samples failed; skipping cycle", sample_count,
                extra={"event": "sensor_error"},
            )
            # Sleep only the *remaining* portion of the interval so that the
            # next publish attempt stays on schedule.  Sleeping the full
            # interval here would add the sample-collection time (~30 s for
            # three 10-second timeouts) on top of the previous cycle's sleep,
            # pushing the gap between publishes to ~136 s and tripping the
            # 120 s stale threshold.
            elapsed = time.monotonic() - cycle_start
            remaining = interval - elapsed
            if remaining > 0:
                _stop.wait(timeout=remaining)
            continue

        # Compute medians.
        co2_ppm = statistics.median(s["co2_ppm"] for s in samples)
        temperature_c = statistics.median(s["temperature_c"] for s in samples)
        humidity_pct = statistics.median(s["humidity_pct"] for s in samples)

        logger.info(
            "Reading: %.0f ppm CO₂  %.2f°C  %.1f%%  (%d/%d samples)",
            co2_ppm,
            temperature_c,
            humidity_pct,
            len(samples),
            sample_count,
            extra={"event": "sensor_read"},
        )

        payload = SCD40Payload(
            sensor_id="scd40",
            timestamp=datetime.now(tz=timezone.utc),
            readings=SCD40Readings(
                co2_ppm=co2_ppm,
                temperature_c=temperature_c,
                humidity_pct=humidity_pct,
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
    logger.info("SCD40 service stopped", extra={"event": "service_stopped"})


if __name__ == "__main__":
    main()
