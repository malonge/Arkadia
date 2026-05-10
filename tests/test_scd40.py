"""Unit tests for the SCD40 sensor service — no hardware required."""

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

SERVICE_DIR = Path(__file__).resolve().parent.parent / "services" / "scd40"

_OTHER_SERVICE_DIRS = [
    Path(__file__).resolve().parent.parent / "services" / "bme280",
]


def _activate_service_path() -> None:
    """Ensure SERVICE_DIR is the active service directory on sys.path."""
    for d in _OTHER_SERVICE_DIRS:
        try:
            sys.path.remove(str(d))
        except ValueError:
            pass
    if sys.path[:1] != [str(SERVICE_DIR)]:
        try:
            sys.path.remove(str(SERVICE_DIR))
        except ValueError:
            pass
        sys.path.insert(0, str(SERVICE_DIR))
    sys.modules.pop("sensor", None)


# ---------------------------------------------------------------------------
# Fake hardware helpers
# ---------------------------------------------------------------------------

def _make_fake_scd4x(co2=415.0, temperature=22.1, humidity=48.3, data_ready=True):
    """Return a fake adafruit_scd4x module and a pre-configured device mock."""
    fake_device = MagicMock()
    fake_device.CO2 = co2
    fake_device.temperature = temperature
    fake_device.relative_humidity = humidity
    # data_ready is a property — configure it via PropertyMock on the type.
    type(fake_device).data_ready = PropertyMock(return_value=data_ready)

    fake_cls = MagicMock(return_value=fake_device)
    fake_mod = types.ModuleType("adafruit_scd4x")
    fake_mod.SCD4X = fake_cls
    return fake_mod, fake_device


def _make_fake_board_busio():
    fake_board = types.ModuleType("board")
    fake_board.SCL = MagicMock(name="SCL")
    fake_board.SDA = MagicMock(name="SDA")
    fake_i2c = MagicMock(name="I2CInstance")
    fake_busio = types.ModuleType("busio")
    fake_busio.I2C = MagicMock(return_value=fake_i2c)
    return fake_board, fake_busio, fake_i2c


def _inject_fakes(co2=415.0, temperature=22.1, humidity=48.3, data_ready=True):
    fake_board, fake_busio, fake_i2c = _make_fake_board_busio()
    fake_mod, fake_device = _make_fake_scd4x(co2, temperature, humidity, data_ready)
    sys.modules.update({
        "board": fake_board,
        "busio": fake_busio,
        "adafruit_scd4x": fake_mod,
    })
    return fake_device, fake_busio, fake_i2c


def _remove_fakes():
    for mod in ("board", "busio", "adafruit_scd4x"):
        sys.modules.pop(mod, None)


# ---------------------------------------------------------------------------
# SCD40Sensor construction
# ---------------------------------------------------------------------------

class TestSCD40SensorConstruction:
    def setup_method(self):
        _activate_service_path()

    def test_default_address(self):
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        assert s._address == 0x62
        assert s._bus == 1

    def test_custom_bus(self):
        from sensor import SCD40Sensor
        s = SCD40Sensor(bus=0, address=0x62)
        assert s._bus == 0

    def test_invalid_address_raises(self):
        from sensor import SCD40Sensor
        from common.i2c import I2CError
        with pytest.raises(I2CError):
            SCD40Sensor(address=0x00)

    def test_no_hardware_on_construction(self):
        _remove_fakes()
        if "sensor" in sys.modules:
            del sys.modules["sensor"]
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        assert s._scd4x is None

    def test_address_keyword_only(self):
        from sensor import SCD40Sensor
        with pytest.raises(TypeError):
            SCD40Sensor(1, 0x62)


# ---------------------------------------------------------------------------
# SCD40Sensor read
# ---------------------------------------------------------------------------

class TestSCD40SensorRead:
    def setup_method(self):
        _activate_service_path()
        _remove_fakes()

    def teardown_method(self):
        _remove_fakes()
        sys.modules.pop("sensor", None)

    def test_read_returns_expected_keys(self):
        _inject_fakes()
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        data = s.read()
        assert set(data.keys()) == {"co2_ppm", "temperature_c", "humidity_pct"}

    def test_read_returns_correct_values(self):
        _inject_fakes(co2=412.0, temperature=21.5, humidity=50.0)
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        data = s.read()
        assert data["co2_ppm"] == pytest.approx(412.0)
        assert data["temperature_c"] == pytest.approx(21.5)
        assert data["humidity_pct"] == pytest.approx(50.0)

    def test_read_values_are_floats(self):
        _inject_fakes(co2=412, temperature=21, humidity=50)
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        data = s.read()
        assert isinstance(data["co2_ppm"], float)
        assert isinstance(data["temperature_c"], float)
        assert isinstance(data["humidity_pct"], float)

    def test_open_inits_hardware(self):
        _, fake_busio, _ = _inject_fakes()
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        assert s._scd4x is None
        s.open()
        assert s._scd4x is not None
        assert fake_busio.I2C.call_count == 1

    def test_read_starts_periodic_measurement(self):
        fake_device, _, _ = _inject_fakes()
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        s.read()
        fake_device.start_periodic_measurement.assert_called_once()

    def test_close_stops_measurement(self):
        fake_device, _, _ = _inject_fakes()
        from sensor import SCD40Sensor
        s = SCD40Sensor()
        s.open()
        s.close()
        fake_device.stop_periodic_measurement.assert_called_once()
        assert s._scd4x is None

    def test_data_ready_timeout_raises_i2c_error(self):
        """If data_ready never becomes True, read() raises I2CError."""
        _inject_fakes(data_ready=False)
        from sensor import SCD40Sensor
        from common.i2c import I2CError
        import sensor as sensor_mod
        # Shorten the timeout for the test.
        original = sensor_mod._DATA_READY_TIMEOUT
        sensor_mod._DATA_READY_TIMEOUT = 0.2
        try:
            s = SCD40Sensor()
            s.open()
            with pytest.raises(I2CError, match="data_ready timeout"):
                s.read()
        finally:
            sensor_mod._DATA_READY_TIMEOUT = original

    def test_partial_init_failure_cleans_up_i2c(self):
        """If SCD4X() raises after the I2C bus opened, self._i2c must be cleaned up."""
        fake_board, fake_busio, fake_i2c = _make_fake_board_busio()
        fail_mod = types.ModuleType("adafruit_scd4x")
        fail_mod.SCD4X = MagicMock(side_effect=RuntimeError("no device"))
        sys.modules.update({
            "board": fake_board,
            "busio": fake_busio,
            "adafruit_scd4x": fail_mod,
        })
        from sensor import SCD40Sensor
        from common.i2c import I2CError
        s = SCD40Sensor()
        with pytest.raises(I2CError):
            s._init_hardware()
        assert s._i2c is None
        assert fake_i2c.deinit.call_count == 1

    def test_read_hardware_error_raises_i2c_error(self):
        _inject_fakes()
        from sensor import SCD40Sensor
        from common.i2c import I2CError
        s = SCD40Sensor()
        s.open()
        type(s._scd4x).CO2 = PropertyMock(side_effect=OSError("bus error"))
        with pytest.raises(I2CError, match="SCD40 read failed"):
            s.read()


# ---------------------------------------------------------------------------
# Payload model validation
# ---------------------------------------------------------------------------

class TestSCD40PayloadBuilding:
    def _make_payload(self, co2=415.0, temperature=22.1, humidity=48.3):
        from common.models import SCD40Payload, SCD40Readings, Diagnostics, Meta
        return SCD40Payload(
            sensor_id="scd40",
            timestamp=datetime(2026, 5, 10, 12, 0, 0, tzinfo=timezone.utc),
            readings=SCD40Readings(
                co2_ppm=co2,
                temperature_c=temperature,
                humidity_pct=humidity,
            ),
            meta=Meta(sample_count=3, aggregation="median"),
            diagnostics=Diagnostics(uptime_seconds=60.0, read_failures=0),
        )

    def test_valid_payload(self):
        p = self._make_payload()
        assert p.sensor_id == "scd40"
        assert p.readings.co2_ppm == 415.0

    def test_json_roundtrip(self):
        from common.models import SCD40Payload
        p = self._make_payload()
        restored = SCD40Payload.model_validate_json(p.model_dump_json())
        assert restored.readings.co2_ppm == pytest.approx(415.0)
        assert restored.readings.temperature_c == pytest.approx(22.1)

    def test_negative_co2_rejected(self):
        with pytest.raises(ValidationError):
            self._make_payload(co2=-1.0)

    def test_humidity_out_of_range(self):
        with pytest.raises(ValidationError):
            self._make_payload(humidity=101.0)

    def test_schema_version(self):
        p = self._make_payload()
        data = json.loads(p.model_dump_json())
        assert data["schema_version"] == 1

    def test_config_topic(self):
        import tomllib
        with (SERVICE_DIR / "config.toml").open("rb") as fh:
            cfg = tomllib.load(fh)
        assert cfg["mqtt"]["topic"] == "home/sensors/air/scd40"
        assert cfg["mqtt"]["retain"] is True
        assert cfg["mqtt"]["qos"] == 1


# ---------------------------------------------------------------------------
# Median aggregation
# ---------------------------------------------------------------------------

class TestMedianAggregation:
    def test_median_of_three(self):
        samples = [
            {"co2_ppm": 410.0, "temperature_c": 21.0, "humidity_pct": 48.0},
            {"co2_ppm": 415.0, "temperature_c": 21.5, "humidity_pct": 49.0},
            {"co2_ppm": 420.0, "temperature_c": 22.0, "humidity_pct": 50.0},
        ]
        assert statistics.median(s["co2_ppm"] for s in samples) == pytest.approx(415.0)
        assert statistics.median(s["temperature_c"] for s in samples) == pytest.approx(21.5)

    def test_median_with_outlier(self):
        samples = [
            {"co2_ppm": 410.0, "temperature_c": 21.0, "humidity_pct": 48.0},
            {"co2_ppm": 415.0, "temperature_c": 21.5, "humidity_pct": 49.0},
            {"co2_ppm": 9999.0, "temperature_c": 99.0, "humidity_pct": 99.0},
        ]
        assert statistics.median(s["co2_ppm"] for s in samples) == pytest.approx(415.0)

    def test_single_surviving_sample(self):
        samples = [{"co2_ppm": 412.0, "temperature_c": 22.0, "humidity_pct": 50.0}]
        assert statistics.median(s["co2_ppm"] for s in samples) == pytest.approx(412.0)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestSCD40Config:
    def test_config_loads(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["sensor"]["i2c_address"] == 0x62
        assert cfg["sensor"]["sample_count"] == 3
        assert cfg["sensor"]["interval_seconds"] == 60
        assert cfg["mqtt"]["topic"] == "home/sensors/air/scd40"

    def test_global_defaults_merged(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["broker"]["host"] == "localhost"
        assert cfg["broker"]["port"] == 1883

    def test_i2c_address_valid(self):
        from common.i2c import I2CBase
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        I2CBase._validate_address(cfg["sensor"]["i2c_address"])
