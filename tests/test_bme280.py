"""Unit tests for the BME280 sensor service — no hardware required.

Strategy: adafruit_bme280, board, and busio are not installed in the CI
environment.  We inject fakes into sys.modules before importing sensor.py
so that the module-level imports (which are deferred to _init_hardware())
resolve to our fakes when the tests force hardware init.
"""

from __future__ import annotations

import json
import statistics
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock

import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Ensure the services/bme280 directory is on sys.path so we can import
# sensor.py and main.py directly (they are not installed packages).
# ---------------------------------------------------------------------------

SERVICE_DIR = Path(__file__).resolve().parent.parent / "services" / "bme280"
if str(SERVICE_DIR) not in sys.path:
    sys.path.insert(0, str(SERVICE_DIR))


# ---------------------------------------------------------------------------
# Fake hardware modules injected into sys.modules
# ---------------------------------------------------------------------------

def _make_fake_adafruit_bme280(temperature=21.5, humidity=55.0, pressure=1013.25):
    """Build a fake adafruit_bme280.basic module whose device returns fixed values."""
    fake_device = MagicMock()
    fake_device.temperature = temperature
    fake_device.relative_humidity = humidity
    fake_device.pressure = pressure

    fake_cls = MagicMock(return_value=fake_device)

    fake_basic = types.ModuleType("adafruit_bme280.basic")
    fake_basic.Adafruit_BME280_I2C = fake_cls

    fake_top = types.ModuleType("adafruit_bme280")
    fake_top.basic = fake_basic

    return fake_top, fake_basic, fake_device


def _make_fake_board_busio():
    fake_board = types.ModuleType("board")
    fake_board.SCL = MagicMock(name="SCL")
    fake_board.SDA = MagicMock(name="SDA")

    fake_i2c_instance = MagicMock(name="I2CInstance")
    fake_busio = types.ModuleType("busio")
    fake_busio.I2C = MagicMock(return_value=fake_i2c_instance)

    return fake_board, fake_busio, fake_i2c_instance


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inject_fakes(temperature=21.5, humidity=55.0, pressure=1013.25):
    """Inject fake hardware modules and return (fake_top, fake_basic, fake_device)."""
    fake_board, fake_busio, fake_i2c = _make_fake_board_busio()
    fake_top, fake_basic, fake_device = _make_fake_adafruit_bme280(
        temperature, humidity, pressure
    )
    sys.modules.update(
        {
            "board": fake_board,
            "busio": fake_busio,
            "adafruit_bme280": fake_top,
            "adafruit_bme280.basic": fake_basic,
        }
    )
    return fake_device, fake_busio


def _remove_fakes():
    for mod in ("board", "busio", "adafruit_bme280", "adafruit_bme280.basic"):
        sys.modules.pop(mod, None)


# ---------------------------------------------------------------------------
# BME280Sensor tests
# ---------------------------------------------------------------------------

class TestBME280SensorConstruction:
    def test_default_address(self):
        from sensor import BME280Sensor
        s = BME280Sensor(address=0x76)
        assert s._address == 0x76
        assert s._bus == 1

    def test_custom_address(self):
        from sensor import BME280Sensor
        s = BME280Sensor(bus=1, address=0x77)
        assert s._address == 0x77

    def test_invalid_address_raises(self):
        from sensor import BME280Sensor
        from common.i2c import I2CError
        with pytest.raises(I2CError):
            BME280Sensor(address=0x00)

    def test_no_hardware_contact_on_construction(self):
        """Constructing BME280Sensor must not touch hardware."""
        _remove_fakes()  # ensure hardware modules are absent
        from sensor import BME280Sensor
        # Should not raise even though adafruit libs are not installed
        s = BME280Sensor(address=0x76)
        assert s._bme280 is None

    def test_address_required_keyword_only(self):
        from sensor import BME280Sensor
        with pytest.raises(TypeError):
            BME280Sensor(1, 0x76)  # positional address not allowed


class TestBME280SensorRead:
    def setup_method(self):
        _remove_fakes()
        # Re-import sensor fresh so module-level state is clean.
        if "sensor" in sys.modules:
            del sys.modules["sensor"]

    def teardown_method(self):
        _remove_fakes()
        if "sensor" in sys.modules:
            del sys.modules["sensor"]

    def test_read_returns_expected_keys(self):
        fake_device, _ = _inject_fakes(temperature=21.5, humidity=55.0, pressure=1013.25)
        from sensor import BME280Sensor
        s = BME280Sensor(address=0x76)
        data = s.read()
        assert set(data.keys()) == {"temperature_c", "humidity_pct", "pressure_hpa"}

    def test_read_values_are_floats(self):
        fake_device, _ = _inject_fakes(temperature=21, humidity=55, pressure=1013)
        from sensor import BME280Sensor
        s = BME280Sensor(address=0x76)
        data = s.read()
        assert isinstance(data["temperature_c"], float)
        assert isinstance(data["humidity_pct"], float)
        assert isinstance(data["pressure_hpa"], float)

    def test_read_returns_correct_values(self):
        fake_device, _ = _inject_fakes(temperature=22.3, humidity=48.7, pressure=1020.1)
        from sensor import BME280Sensor
        s = BME280Sensor(address=0x76)
        data = s.read()
        assert data["temperature_c"] == pytest.approx(22.3, abs=0.01)
        assert data["humidity_pct"] == pytest.approx(48.7, abs=0.01)
        assert data["pressure_hpa"] == pytest.approx(1020.1, abs=0.01)

    def test_read_inits_hardware_lazily(self):
        fake_device, fake_busio = _inject_fakes()
        from sensor import BME280Sensor
        s = BME280Sensor(address=0x76)
        assert s._bme280 is None  # not yet initialised
        s.read()
        assert s._bme280 is not None  # initialised on first read
        assert fake_busio.I2C.call_count == 1

    def test_open_inits_hardware_eagerly(self):
        fake_device, fake_busio = _inject_fakes()
        from sensor import BME280Sensor
        s = BME280Sensor(address=0x76)
        s.open()
        assert s._bme280 is not None
        assert fake_busio.I2C.call_count == 1

    def test_read_hardware_error_raises_i2c_error(self):
        _inject_fakes()
        from sensor import BME280Sensor
        from common.i2c import I2CError
        s = BME280Sensor(address=0x76)
        s.open()
        # Make the .temperature property raise on access (not on call).
        type(s._bme280).temperature = PropertyMock(side_effect=OSError("I2C failure"))
        with pytest.raises(I2CError, match="BME280 read failed"):
            s.read()

    def test_close_clears_bme280(self):
        _inject_fakes()
        from sensor import BME280Sensor
        s = BME280Sensor(address=0x76)
        s.open()
        assert s._bme280 is not None
        s.close()
        assert s._bme280 is None


# ---------------------------------------------------------------------------
# Payload model validation (core correctness check for real Pi data)
# ---------------------------------------------------------------------------

class TestBME280PayloadBuilding:
    """Verify that the values produced by a sensor read pass Pydantic validation."""

    def _make_payload(self, temperature_c=21.5, humidity_pct=55.0, pressure_hpa=1013.25):
        from common.models import BME280Payload, BME280Readings, Diagnostics, Meta
        return BME280Payload(
            sensor_id="bme280",
            timestamp=datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc),
            readings=BME280Readings(
                temperature_c=temperature_c,
                humidity_pct=humidity_pct,
                pressure_hpa=pressure_hpa,
            ),
            meta=Meta(sample_count=5, aggregation="median"),
            diagnostics=Diagnostics(uptime_seconds=120.0, read_failures=0),
        )

    def test_valid_payload(self):
        p = self._make_payload()
        assert p.sensor_id == "bme280"
        assert p.readings.temperature_c == 21.5

    def test_payload_json_roundtrip(self):
        from common.models import BME280Payload
        p = self._make_payload()
        restored = BME280Payload.model_validate_json(p.model_dump_json())
        assert restored.readings.pressure_hpa == pytest.approx(1013.25)

    def test_invalid_humidity_rejected(self):
        with pytest.raises(ValidationError):
            self._make_payload(humidity_pct=105.0)

    def test_invalid_pressure_rejected(self):
        with pytest.raises(ValidationError):
            self._make_payload(pressure_hpa=0.0)

    def test_payload_schema_version(self):
        p = self._make_payload()
        data = json.loads(p.model_dump_json())
        assert data["schema_version"] == 1

    def test_payload_topic_in_config(self):
        """Smoke-test that the config.toml topic matches the expected MQTT path."""
        import tomllib
        config_path = SERVICE_DIR / "config.toml"
        with config_path.open("rb") as fh:
            cfg = tomllib.load(fh)
        assert cfg["mqtt"]["topic"] == "home/sensors/climate/bme280"
        assert cfg["mqtt"]["retain"] is True
        assert cfg["mqtt"]["qos"] == 1


# ---------------------------------------------------------------------------
# Median aggregation logic
# ---------------------------------------------------------------------------

class TestMedianAggregation:
    """Test the aggregation logic used in main.py independent of hardware."""

    def test_median_of_five(self):
        samples = [
            {"temperature_c": 21.0, "humidity_pct": 50.0, "pressure_hpa": 1010.0},
            {"temperature_c": 21.2, "humidity_pct": 51.0, "pressure_hpa": 1011.0},
            {"temperature_c": 21.4, "humidity_pct": 52.0, "pressure_hpa": 1012.0},
            {"temperature_c": 21.6, "humidity_pct": 53.0, "pressure_hpa": 1013.0},
            {"temperature_c": 21.8, "humidity_pct": 54.0, "pressure_hpa": 1014.0},
        ]
        temp = statistics.median(s["temperature_c"] for s in samples)
        hum = statistics.median(s["humidity_pct"] for s in samples)
        pres = statistics.median(s["pressure_hpa"] for s in samples)
        assert temp == pytest.approx(21.4)
        assert hum == pytest.approx(52.0)
        assert pres == pytest.approx(1012.0)

    def test_median_with_outlier(self):
        """Median should be robust to a single outlier reading."""
        samples = [
            {"temperature_c": 21.0, "humidity_pct": 50.0, "pressure_hpa": 1010.0},
            {"temperature_c": 21.1, "humidity_pct": 50.5, "pressure_hpa": 1010.5},
            {"temperature_c": 99.9, "humidity_pct": 99.9, "pressure_hpa": 9999.0},  # outlier
            {"temperature_c": 21.2, "humidity_pct": 50.8, "pressure_hpa": 1011.0},
            {"temperature_c": 21.3, "humidity_pct": 51.0, "pressure_hpa": 1011.5},
        ]
        temp = statistics.median(s["temperature_c"] for s in samples)
        assert temp == pytest.approx(21.2)

    def test_median_with_partial_failures(self):
        """If some samples fail, median is computed on the survivors."""
        samples = [
            {"temperature_c": 20.0, "humidity_pct": 48.0, "pressure_hpa": 1009.0},
            {"temperature_c": 20.2, "humidity_pct": 49.0, "pressure_hpa": 1010.0},
            # one sample dropped due to read failure
        ]
        temp = statistics.median(s["temperature_c"] for s in samples)
        assert temp == pytest.approx(20.1)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestBME280Config:
    def test_config_loads_without_error(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["sensor"]["i2c_bus"] == 1
        assert cfg["sensor"]["i2c_address"] == 0x76
        assert cfg["sensor"]["sample_count"] == 5
        assert cfg["sensor"]["interval_seconds"] == 30
        assert cfg["mqtt"]["topic"] == "home/sensors/climate/bme280"

    def test_global_broker_defaults_merged(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        # Global defaults should be present after merge
        assert cfg["broker"]["host"] == "localhost"
        assert cfg["broker"]["port"] == 1883

    def test_i2c_address_is_valid(self):
        """The configured I2C address must be accepted by I2CBase._validate_address."""
        from common.i2c import I2CBase
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        # Should not raise
        I2CBase._validate_address(cfg["sensor"]["i2c_address"])
