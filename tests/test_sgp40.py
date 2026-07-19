"""Unit tests for the SGP40 sensor service — no hardware required."""

from __future__ import annotations

import json
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError

SERVICE_DIR = Path(__file__).resolve().parent.parent / "services" / "sgp40"


def _activate_service_path() -> None:
    for other in ["services/bme280", "services/scd40"]:
        p = str(Path(__file__).resolve().parent.parent / other)
        try:
            sys.path.remove(p)
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

def _make_fake_sgp40(voc_index: int = 97):
    fake_device = MagicMock()
    fake_device.measure_index.return_value = voc_index

    fake_cls = MagicMock(return_value=fake_device)
    fake_mod = types.ModuleType("adafruit_sgp40")
    fake_mod.SGP40 = fake_cls
    return fake_mod, fake_device


def _make_fake_board_busio():
    fake_board = types.ModuleType("board")
    fake_board.SCL = MagicMock(name="SCL")
    fake_board.SDA = MagicMock(name="SDA")
    fake_i2c = MagicMock(name="I2CInstance")
    fake_busio = types.ModuleType("busio")
    fake_busio.I2C = MagicMock(return_value=fake_i2c)
    return fake_board, fake_busio, fake_i2c


def _inject_fakes(voc_index: int = 97):
    fake_board, fake_busio, fake_i2c = _make_fake_board_busio()
    fake_mod, fake_device = _make_fake_sgp40(voc_index)
    sys.modules.update({
        "board": fake_board,
        "busio": fake_busio,
        "adafruit_sgp40": fake_mod,
    })
    return fake_device, fake_busio, fake_i2c


def _remove_fakes():
    for mod in ("board", "busio", "adafruit_sgp40"):
        sys.modules.pop(mod, None)


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------

class TestSGP40SensorConstruction:
    def setup_method(self):
        _activate_service_path()
        _remove_fakes()

    def test_fixed_address(self):
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        assert s._address == 0x59

    def test_custom_bus(self):
        from sensor import SGP40Sensor
        s = SGP40Sensor(bus=0, address=0x59)
        assert s._bus == 0

    def test_no_hardware_on_construction(self):
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        assert s._sgp40 is None

    def test_address_keyword_only(self):
        from sensor import SGP40Sensor
        with pytest.raises(TypeError):
            SGP40Sensor(1, 0x59)  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Hardware initialisation and reads
# ---------------------------------------------------------------------------

class TestSGP40SensorRead:
    def setup_method(self):
        _activate_service_path()
        _remove_fakes()

    def test_open_inits_hardware(self):
        _, fake_busio, _ = _inject_fakes()
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        assert s._sgp40 is None
        s.open()
        assert s._sgp40 is not None
        assert fake_busio.I2C.call_count == 1

    def test_read_returns_voc_index_key(self):
        _inject_fakes(voc_index=120)
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        result = s.read()
        assert "voc_index" in result

    def test_read_returns_correct_value(self):
        _inject_fakes(voc_index=143)
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        result = s.read()
        assert result["voc_index"] == 143

    def test_read_value_is_int(self):
        _inject_fakes(voc_index=97)
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        result = s.read()
        assert isinstance(result["voc_index"], int)

    def test_read_calls_measure_index(self):
        fake_device, _, _ = _inject_fakes()
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        s.read()
        fake_device.measure_index.assert_called()

    def test_close_releases_device(self):
        _inject_fakes()
        from sensor import SGP40Sensor
        s = SGP40Sensor()
        s.open()
        assert s._sgp40 is not None
        s.close()
        assert s._sgp40 is None

    def test_read_hardware_error_raises_i2c_error(self):
        fake_device, _, _ = _inject_fakes()
        fake_device.measure_index.side_effect = RuntimeError("bus fault")
        from sensor import SGP40Sensor
        from common.i2c import I2CError
        s = SGP40Sensor()
        with pytest.raises(I2CError, match="SGP40 read failed"):
            s.read()

    def test_partial_init_failure_cleans_up_i2c(self):
        fake_board, fake_busio, fake_i2c = _make_fake_board_busio()
        fail_mod = types.ModuleType("adafruit_sgp40")
        fail_mod.SGP40 = MagicMock(side_effect=RuntimeError("no device"))
        sys.modules.update({
            "board": fake_board,
            "busio": fake_busio,
            "adafruit_sgp40": fail_mod,
        })
        _activate_service_path()
        from sensor import SGP40Sensor
        from common.i2c import I2CError
        s = SGP40Sensor()
        with pytest.raises(I2CError):
            s.open()
        assert s._i2c is None
        assert s._sgp40 is None


# ---------------------------------------------------------------------------
# Payload building
# ---------------------------------------------------------------------------

class TestSGP40PayloadBuilding:
    def test_valid_payload(self):
        from common.models import SGP40Payload, SGP40Readings, Meta

        p = SGP40Payload(
            sensor_id="sgp40",
            timestamp=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
            readings=SGP40Readings(voc_index=97),
            meta=Meta(sample_count=1, aggregation="latest"),
        )
        assert p.readings.voc_index == 97
        assert p.sensor_id == "sgp40"

    def test_json_roundtrip(self):
        from common.models import SGP40Payload, SGP40Readings, Meta

        p = SGP40Payload(
            sensor_id="sgp40",
            timestamp=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
            readings=SGP40Readings(voc_index=200),
            meta=Meta(sample_count=1, aggregation="latest"),
        )
        d = json.loads(p.model_dump_json())
        assert d["readings"]["voc_index"] == 200
        assert d["schema_version"] == 1

    def test_voc_index_below_zero_rejected(self):
        from common.models import SGP40Readings
        with pytest.raises(ValidationError):
            SGP40Readings(voc_index=-1)

    def test_voc_index_above_500_rejected(self):
        from common.models import SGP40Readings
        with pytest.raises(ValidationError):
            SGP40Readings(voc_index=501)

    def test_voc_index_boundary_values_accepted(self):
        from common.models import SGP40Readings
        assert SGP40Readings(voc_index=0).voc_index == 0
        assert SGP40Readings(voc_index=500).voc_index == 500

    def test_wrong_sensor_id(self):
        from common.models import SGP40Payload, SGP40Readings, Meta
        with pytest.raises(ValidationError):
            SGP40Payload(
                sensor_id="bme280",
                timestamp=datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc),
                readings=SGP40Readings(voc_index=100),
                meta=Meta(sample_count=1, aggregation="latest"),
            )


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestSGP40Config:
    def test_config_loads(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["sensor"]["i2c_address"] == 0x59
        assert cfg["sensor"]["publish_interval_seconds"] == 60
        assert cfg["mqtt"]["topic"] == "home/sensors/air/sgp40"

    def test_global_defaults_merged(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["broker"]["host"] == "localhost"
        assert cfg["broker"]["port"] == 1883
