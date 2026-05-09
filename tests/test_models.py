"""Unit tests for common/models.py — no hardware required."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from common.models import (
    AudioPayload,
    AudioReadings,
    BME280Payload,
    BME280Readings,
    Diagnostics,
    Meta,
    SCD40Payload,
    SCD40Readings,
    SensorPayload,
)


# ---------------------------------------------------------------------------
# Meta
# ---------------------------------------------------------------------------


class TestMeta:
    def test_valid(self):
        m = Meta(sample_count=5, aggregation="median")
        assert m.sample_count == 5
        assert m.aggregation == "median"

    def test_zero_sample_count(self):
        with pytest.raises(ValidationError):
            Meta(sample_count=0, aggregation="median")

    def test_negative_sample_count(self):
        with pytest.raises(ValidationError):
            Meta(sample_count=-1, aggregation="median")


# ---------------------------------------------------------------------------
# Diagnostics
# ---------------------------------------------------------------------------


class TestDiagnostics:
    def test_valid(self):
        d = Diagnostics(uptime_seconds=1234.5, read_failures=0)
        assert d.uptime_seconds == 1234.5
        assert d.read_failures == 0

    def test_negative_uptime(self):
        with pytest.raises(ValidationError):
            Diagnostics(uptime_seconds=-1)

    def test_negative_read_failures(self):
        with pytest.raises(ValidationError):
            Diagnostics(uptime_seconds=0, read_failures=-1)


# ---------------------------------------------------------------------------
# BME280Readings
# ---------------------------------------------------------------------------


class TestBME280Readings:
    def test_valid(self):
        r = BME280Readings(temperature_c=21.4, humidity_pct=55.2, pressure_hpa=1013.25)
        assert r.temperature_c == 21.4

    def test_humidity_out_of_range_high(self):
        with pytest.raises(ValidationError):
            BME280Readings(temperature_c=20, humidity_pct=101, pressure_hpa=1000)

    def test_humidity_out_of_range_low(self):
        with pytest.raises(ValidationError):
            BME280Readings(temperature_c=20, humidity_pct=-1, pressure_hpa=1000)

    def test_pressure_zero(self):
        with pytest.raises(ValidationError):
            BME280Readings(temperature_c=20, humidity_pct=50, pressure_hpa=0)


# ---------------------------------------------------------------------------
# SCD40Readings
# ---------------------------------------------------------------------------


class TestSCD40Readings:
    def test_valid_minimal(self):
        r = SCD40Readings(co2_ppm=412.5)
        assert r.co2_ppm == 412.5
        assert r.temperature_c is None
        assert r.humidity_pct is None

    def test_valid_full(self):
        r = SCD40Readings(co2_ppm=412.5, temperature_c=22.1, humidity_pct=48.3)
        assert r.temperature_c == 22.1

    def test_negative_co2(self):
        with pytest.raises(ValidationError):
            SCD40Readings(co2_ppm=-1)


# ---------------------------------------------------------------------------
# AudioReadings
# ---------------------------------------------------------------------------


class TestAudioReadings:
    def test_valid(self):
        r = AudioReadings(rms_amplitude=0.05, db_level=-26.0)
        assert r.rms_amplitude == 0.05

    def test_negative_rms(self):
        with pytest.raises(ValidationError):
            AudioReadings(rms_amplitude=-0.1, db_level=-26.0)


# ---------------------------------------------------------------------------
# SensorPayload (generic envelope)
# ---------------------------------------------------------------------------

NOW_UTC = datetime(2026, 5, 8, 14, 23, 1, tzinfo=timezone.utc)


class TestSensorPayload:
    def _bme280_payload_data(self):
        return {
            "schema_version": 1,
            "sensor_id": "bme280",
            "timestamp": NOW_UTC,
            "readings": BME280Readings(temperature_c=21.4, humidity_pct=55.2, pressure_hpa=1013.25),
            "meta": Meta(sample_count=5, aggregation="median"),
        }

    def test_valid_without_diagnostics(self):
        p = SensorPayload(**self._bme280_payload_data())
        assert p.schema_version == 1
        assert p.sensor_id == "bme280"
        assert p.diagnostics is None

    def test_valid_with_diagnostics(self):
        data = self._bme280_payload_data()
        data["diagnostics"] = Diagnostics(uptime_seconds=3600, read_failures=2)
        p = SensorPayload(**data)
        assert p.diagnostics.read_failures == 2

    def test_naive_timestamp_gets_utc(self):
        data = self._bme280_payload_data()
        data["timestamp"] = datetime(2026, 5, 8, 14, 23, 1)  # naive
        p = SensorPayload(**data)
        assert p.timestamp.tzinfo == timezone.utc

    def test_wrong_schema_version(self):
        data = self._bme280_payload_data()
        data["schema_version"] = 2  # only 1 is valid
        with pytest.raises(ValidationError):
            SensorPayload(**data)

    def test_empty_sensor_id(self):
        data = self._bme280_payload_data()
        data["sensor_id"] = ""
        with pytest.raises(ValidationError):
            SensorPayload(**data)


# ---------------------------------------------------------------------------
# Sensor-specific typed payloads
# ---------------------------------------------------------------------------


class TestBME280Payload:
    def test_valid(self):
        p = BME280Payload(
            sensor_id="bme280",
            timestamp=NOW_UTC,
            readings=BME280Readings(temperature_c=21.4, humidity_pct=55.2, pressure_hpa=1013.25),
            meta=Meta(sample_count=5, aggregation="median"),
        )
        assert p.sensor_id == "bme280"

    def test_wrong_sensor_id(self):
        with pytest.raises(ValidationError):
            BME280Payload(
                sensor_id="scd40",
                timestamp=NOW_UTC,
                readings=BME280Readings(temperature_c=21.4, humidity_pct=55.2, pressure_hpa=1013.25),
                meta=Meta(sample_count=5, aggregation="median"),
            )


class TestSCD40Payload:
    def test_valid(self):
        p = SCD40Payload(
            sensor_id="scd40",
            timestamp=NOW_UTC,
            readings=SCD40Readings(co2_ppm=415.0),
            meta=Meta(sample_count=3, aggregation="median"),
        )
        assert p.readings.co2_ppm == 415.0

    def test_wrong_sensor_id(self):
        with pytest.raises(ValidationError):
            SCD40Payload(
                sensor_id="bme280",
                timestamp=NOW_UTC,
                readings=SCD40Readings(co2_ppm=415.0),
                meta=Meta(sample_count=3, aggregation="median"),
            )


class TestAudioPayload:
    def test_valid(self):
        p = AudioPayload(
            sensor_id="inmp441",
            timestamp=NOW_UTC,
            readings=AudioReadings(rms_amplitude=0.03, db_level=-30.5),
            meta=Meta(sample_count=1, aggregation="rms"),
        )
        assert p.sensor_id == "inmp441"

    def test_wrong_sensor_id(self):
        with pytest.raises(ValidationError):
            AudioPayload(
                sensor_id="microphone",
                timestamp=NOW_UTC,
                readings=AudioReadings(rms_amplitude=0.03, db_level=-30.5),
                meta=Meta(sample_count=1, aggregation="rms"),
            )


# ---------------------------------------------------------------------------
# Round-trip JSON serialisation
# ---------------------------------------------------------------------------


class TestJSONRoundTrip:
    def test_bme280_roundtrip(self):
        p = BME280Payload(
            sensor_id="bme280",
            timestamp=NOW_UTC,
            readings=BME280Readings(temperature_c=21.4, humidity_pct=55.2, pressure_hpa=1013.25),
            meta=Meta(sample_count=5, aggregation="median"),
            diagnostics=Diagnostics(uptime_seconds=100, read_failures=0),
        )
        json_str = p.model_dump_json()
        restored = BME280Payload.model_validate_json(json_str)
        assert restored.readings.temperature_c == p.readings.temperature_c
        assert restored.diagnostics.uptime_seconds == p.diagnostics.uptime_seconds

    def test_audio_roundtrip(self):
        p = AudioPayload(
            sensor_id="inmp441",
            timestamp=NOW_UTC,
            readings=AudioReadings(rms_amplitude=0.05, db_level=-20.0),
            meta=Meta(sample_count=1, aggregation="rms"),
        )
        json_str = p.model_dump_json()
        restored = AudioPayload.model_validate_json(json_str)
        assert restored.readings.db_level == p.readings.db_level
