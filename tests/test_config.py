"""Unit tests for common/config.py — no hardware required."""

import textwrap
from pathlib import Path

import pytest

from common.config import (
    BrokerConfig,
    GlobalConfig,
    LoggingConfig,
    _deep_merge,
    load_config,
    load_global_config,
)


# ---------------------------------------------------------------------------
# BrokerConfig validation
# ---------------------------------------------------------------------------


class TestBrokerConfig:
    def test_defaults(self):
        cfg = BrokerConfig()
        assert cfg.host == "localhost"
        assert cfg.port == 1883
        assert cfg.keepalive == 60

    def test_custom_values(self):
        cfg = BrokerConfig(host="192.168.1.1", port=8883, keepalive=30)
        assert cfg.host == "192.168.1.1"
        assert cfg.port == 8883
        assert cfg.keepalive == 30

    def test_port_too_low(self):
        with pytest.raises(ValueError, match="port must be"):
            BrokerConfig(port=0)

    def test_port_too_high(self):
        with pytest.raises(ValueError, match="port must be"):
            BrokerConfig(port=70000)

    def test_keepalive_zero(self):
        with pytest.raises(ValueError, match="keepalive must be positive"):
            BrokerConfig(keepalive=0)

    def test_keepalive_negative(self):
        with pytest.raises(ValueError, match="keepalive must be positive"):
            BrokerConfig(keepalive=-1)


# ---------------------------------------------------------------------------
# LoggingConfig validation
# ---------------------------------------------------------------------------


class TestLoggingConfig:
    def test_defaults(self):
        cfg = LoggingConfig()
        assert cfg.level == "INFO"
        assert cfg.format == "json"

    def test_level_normalised_to_upper(self):
        cfg = LoggingConfig(level="debug")
        assert cfg.level == "DEBUG"

    def test_format_normalised_to_lower(self):
        cfg = LoggingConfig(format="JSON")
        assert cfg.format == "json"

    def test_invalid_level(self):
        with pytest.raises(ValueError, match="level must be one of"):
            LoggingConfig(level="VERBOSE")

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="format must be one of"):
            LoggingConfig(format="yaml")


# ---------------------------------------------------------------------------
# GlobalConfig
# ---------------------------------------------------------------------------


class TestGlobalConfig:
    def test_defaults(self):
        cfg = GlobalConfig()
        assert cfg.broker.host == "localhost"
        assert cfg.logging.level == "INFO"

    def test_partial_override(self):
        cfg = GlobalConfig(broker={"host": "mqtt.local", "port": 1883, "keepalive": 60})
        assert cfg.broker.host == "mqtt.local"


# ---------------------------------------------------------------------------
# _deep_merge
# ---------------------------------------------------------------------------


class TestDeepMerge:
    def test_simple_override(self):
        base = {"a": 1, "b": 2}
        override = {"b": 99, "c": 3}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_nested_merge(self):
        base = {"broker": {"host": "localhost", "port": 1883}}
        override = {"broker": {"port": 8883}}
        result = _deep_merge(base, override)
        assert result == {"broker": {"host": "localhost", "port": 8883}}

    def test_base_not_mutated(self):
        base = {"a": {"x": 1}}
        override = {"a": {"x": 2}}
        _deep_merge(base, override)
        assert base["a"]["x"] == 1  # base is unchanged

    def test_override_adds_new_key(self):
        base = {"a": 1}
        override = {"b": 2}
        result = _deep_merge(base, override)
        assert result == {"a": 1, "b": 2}


# ---------------------------------------------------------------------------
# load_global_config
# ---------------------------------------------------------------------------


class TestLoadGlobalConfig:
    def test_loads_real_global_toml(self):
        """Load the actual config/global.toml in the repo."""
        repo_root = Path(__file__).resolve().parent.parent
        cfg = load_global_config(repo_root / "config" / "global.toml")
        assert cfg.broker.host == "localhost"
        assert cfg.broker.port == 1883
        assert cfg.logging.format == "json"

    def test_missing_file_returns_defaults(self, tmp_path):
        missing = tmp_path / "nonexistent.toml"
        cfg = load_global_config(missing)
        assert cfg == GlobalConfig()

    def test_partial_global_file(self, tmp_path):
        toml_file = tmp_path / "global.toml"
        toml_file.write_text(
            textwrap.dedent("""\
                [broker]
                host = "mqtt.example.com"
            """)
        )
        cfg = load_global_config(toml_file)
        assert cfg.broker.host == "mqtt.example.com"
        assert cfg.broker.port == 1883  # default

    def test_invalid_global_file(self, tmp_path):
        toml_file = tmp_path / "global.toml"
        toml_file.write_text(
            textwrap.dedent("""\
                [broker]
                port = 99999
            """)
        )
        with pytest.raises(ValueError):
            load_global_config(toml_file)


# ---------------------------------------------------------------------------
# load_config
# ---------------------------------------------------------------------------


class TestLoadConfig:
    def test_local_overrides_global(self, tmp_path):
        global_file = tmp_path / "global.toml"
        global_file.write_text(
            textwrap.dedent("""\
                [broker]
                host = "localhost"
                port = 1883
                keepalive = 60

                [logging]
                level = "INFO"
                format = "json"
            """)
        )
        local_file = tmp_path / "local.toml"
        local_file.write_text(
            textwrap.dedent("""\
                [broker]
                port = 8883

                [sensor]
                interval_seconds = 30
            """)
        )
        merged = load_config(local_file, global_path=global_file)
        assert merged["broker"]["host"] == "localhost"  # from global
        assert merged["broker"]["port"] == 8883          # overridden by local
        assert merged["sensor"]["interval_seconds"] == 30  # local-only key

    def test_missing_local_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "missing.toml")

    def test_no_global_path_uses_repo_default(self, tmp_path):
        """When global_path is omitted the repo's global.toml should be used."""
        local_file = tmp_path / "service.toml"
        local_file.write_text("[mqtt]\ntopic = \"home/sensors/test\"\n")
        merged = load_config(local_file)
        assert merged["broker"]["host"] == "localhost"
        assert merged["mqtt"]["topic"] == "home/sensors/test"
