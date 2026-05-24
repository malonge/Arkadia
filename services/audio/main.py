"""Audio sensor service.

Publish loop
------------
Each iteration of the main loop blocks in ``sensor.read_frame()`` for
approximately ``window_size / sample_rate_hz`` seconds (50 ms at the
default settings of 800 samples @ 16 kHz).

Stream publish (every frame)
    Topic: ``home/sensors/audio/inmp441/stream``
    QoS 0, retain=false
    Payload: AudioStreamPayload (waveform, FFT bins, EQ bands, RMS)

Summary publish (every summary_interval_seconds)
    Topic: ``home/sensors/audio/inmp441``
    QoS 1, retain=true
    Payload: AudioPayload (energy-averaged RMS and dBFS)

Shutdown
--------
SIGTERM or SIGINT sets ``_stop``, which is checked at the top of the loop.
Since ``read_frame()`` is a blocking call, shutdown completes within one
frame duration (~50 ms) after the signal is received.
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
from common.models import AudioPayload, AudioStreamPayload, Diagnostics, Meta, StreamMeta
from common.mqtt import MQTTClient, configure_logging

sys.path.insert(0, str(Path(__file__).parent))

from sensor import AudioError, AudioSensor, compute_summary_rms

logger = logging.getLogger("audio")

_stop = threading.Event()


def _handle_signal(signum: int, frame: object) -> None:
    logger.info(
        "Signal %d received — shutting down", signum,
        extra={"event": "service_shutdown"},
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

    logger.info("Audio service starting", extra={"event": "service_started"})
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

    client = MQTTClient(
        client_id=mqtt_cfg["client_id"],
        broker_host=broker["host"],
        broker_port=broker["port"],
        keepalive=broker["keepalive"],
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

    eq_bands_hz: list[float] = [
        float(b) for b in sensor_cfg.get(
            "eq_bands_hz", [63, 125, 250, 500, 1000, 2000, 4000, 8000]
        )
    ]

    sensor = AudioSensor(
        device_index=sensor_cfg.get("device_index", 0),
        sample_rate_hz=int(sensor_cfg.get("sample_rate_hz", 16000)),
        window_size=int(sensor_cfg.get("window_size", 800)),
        window_function=str(sensor_cfg.get("window_function", "hann")),
        eq_bands_hz=eq_bands_hz,
    )

    try:
        sensor.open()
    except AudioError as exc:
        logger.critical(
            "Audio device init failed: %s", exc,
            extra={"event": "sensor_error"},
        )
        client.loop_stop()
        sys.exit(1)

    # ----------------------------------------------------------------
    # Publish settings
    # ----------------------------------------------------------------
    summary_topic: str = mqtt_cfg["summary_topic"]
    stream_topic: str = mqtt_cfg["stream_topic"]
    summary_interval: float = float(
        sensor_cfg.get("summary_interval_seconds", 5.0)
    )
    window_function: str = str(sensor_cfg.get("window_function", "hann"))

    # ----------------------------------------------------------------
    # Main loop
    # ----------------------------------------------------------------
    service_start = time.monotonic()
    last_summary_time = time.monotonic()
    read_failures = 0
    frame_count = 0

    # Accumulators for energy-average summary RMS.
    sum_sq_rms = 0.0
    n_frames_accumulated = 0

    logger.info(
        "Entering stream loop (window=%d samples, interval=%.0fs)",
        sensor.window_size,
        summary_interval,
        extra={"event": "poll_loop_start"},
    )

    while not _stop.is_set():
        # --- Read one audio frame (blocks for ~window_size/sample_rate s) ---
        try:
            stream_readings = sensor.read_frame()
        except AudioError as exc:
            read_failures += 1
            logger.error(
                "Audio read error: %s (total failures: %d)",
                exc,
                read_failures,
                extra={"event": "sensor_error"},
            )
            # Brief sleep to avoid spinning on repeated device errors.
            _stop.wait(timeout=1.0)
            continue

        frame_count += 1

        # --- Stream publish (QoS 0, no retain) ---
        stream_payload = AudioStreamPayload(
            sensor_id="inmp441",
            timestamp=datetime.now(tz=timezone.utc),
            readings=stream_readings,
            meta=StreamMeta(
                sample_count=sensor.window_size,
                aggregation="fft",
                window_function=window_function,
            ),
            diagnostics=Diagnostics(
                uptime_seconds=time.monotonic() - service_start,
                read_failures=read_failures,
            ),
        )

        try:
            client.publish(
                stream_topic,
                stream_payload.model_dump_json(),
                qos=0,
                retain=False,
            )
        except RuntimeError as exc:
            logger.error(
                "Stream publish failed: %s", exc,
                extra={"event": "mqtt_publish_error"},
            )

        logger.debug(
            "Frame %d: rms=%.4f dBFS=%.1f",
            frame_count,
            stream_readings.rms_amplitude,
            stream_readings.db_level,
            extra={"event": "sensor_read"},
        )

        # --- Accumulate for summary ---
        sum_sq_rms += stream_readings.rms_amplitude ** 2
        n_frames_accumulated += 1

        # --- Summary publish ---
        now = time.monotonic()
        if now - last_summary_time >= summary_interval and n_frames_accumulated > 0:
            summary_readings = compute_summary_rms(sum_sq_rms, n_frames_accumulated)

            summary_payload = AudioPayload(
                sensor_id="inmp441",
                timestamp=datetime.now(tz=timezone.utc),
                readings=summary_readings,
                meta=Meta(
                    sample_count=n_frames_accumulated * sensor.window_size,
                    aggregation="rms",
                ),
                diagnostics=Diagnostics(
                    uptime_seconds=now - service_start,
                    read_failures=read_failures,
                ),
            )

            try:
                client.publish(
                    summary_topic,
                    summary_payload.model_dump_json(),
                    qos=1,
                    retain=True,
                )
                logger.info(
                    "Summary: rms=%.4f dBFS=%.1f (frames=%d, failures=%d)",
                    summary_readings.rms_amplitude,
                    summary_readings.db_level,
                    n_frames_accumulated,
                    read_failures,
                    extra={"event": "mqtt_publish"},
                )
            except RuntimeError as exc:
                logger.error(
                    "Summary publish failed: %s", exc,
                    extra={"event": "mqtt_publish_error"},
                )

            # Reset accumulators for the next summary window.
            sum_sq_rms = 0.0
            n_frames_accumulated = 0
            last_summary_time = now

    # ----------------------------------------------------------------
    # Shutdown
    # ----------------------------------------------------------------
    logger.info("Stopping stream loop", extra={"event": "service_shutdown"})
    sensor.close()
    client.loop_stop()
    client.disconnect()
    logger.info(
        "Audio service stopped (frames=%d, failures=%d)",
        frame_count,
        read_failures,
        extra={"event": "service_stopped"},
    )


if __name__ == "__main__":
    main()
