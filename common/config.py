"""TOML configuration loader with global/local merge and typed config objects."""

import tomllib
from pathlib import Path
from typing import Any

from pydantic import BaseModel, field_validator


# ---------------------------------------------------------------------------
# Typed config objects
# ---------------------------------------------------------------------------


class BrokerConfig(BaseModel):
    host: str = "localhost"
    port: int = 1883
    keepalive: int = 60

    @field_validator("port")
    @classmethod
    def port_in_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"port must be 1–65535, got {v}")
        return v

    @field_validator("keepalive")
    @classmethod
    def keepalive_positive(cls, v: int) -> int:
        if v <= 0:
            raise ValueError(f"keepalive must be positive, got {v}")
        return v


class LoggingConfig(BaseModel):
    level: str = "INFO"
    format: str = "json"

    @field_validator("level")
    @classmethod
    def level_valid(cls, v: str) -> str:
        valid = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        upper = v.upper()
        if upper not in valid:
            raise ValueError(f"level must be one of {valid}, got {v!r}")
        return upper

    @field_validator("format")
    @classmethod
    def format_valid(cls, v: str) -> str:
        valid = {"json", "text"}
        lower = v.lower()
        if lower not in valid:
            raise ValueError(f"format must be one of {valid}, got {v!r}")
        return lower


class GlobalConfig(BaseModel):
    broker: BrokerConfig = BrokerConfig()
    logging: LoggingConfig = LoggingConfig()


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file and return its contents as a dict."""
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge *override* into *base*, returning a new dict."""
    result: dict[str, Any] = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_global_config(global_path: Path | str | None = None) -> GlobalConfig:
    """Load and validate the global configuration file.

    If *global_path* is not provided the default ``config/global.toml``
    relative to the repository root is used.  A missing file is treated as an
    empty config (all defaults apply).
    """
    if global_path is None:
        # Walk up from this file's location to find the repo root.
        repo_root = Path(__file__).resolve().parent.parent
        global_path = repo_root / "config" / "global.toml"

    global_path = Path(global_path)
    raw: dict[str, Any] = _load_toml(global_path) if global_path.exists() else {}
    return GlobalConfig.model_validate(raw)


def load_config(
    local_path: Path | str,
    global_path: Path | str | None = None,
) -> dict[str, Any]:
    """Load and merge global config with a service-local config file.

    The global config is loaded first and validated as a :class:`GlobalConfig`
    (so invalid ``[broker]`` or ``[logging]`` values in the *global* file are
    caught immediately).  The local config is then deep-merged on top, with
    local values taking precedence.

    The merged result is returned as a raw ``dict``; callers are responsible
    for constructing and validating any typed objects they need.  In particular,
    if the local file overrides ``[broker]`` or ``[logging]`` keys, those
    overrides are **not** re-validated here.

    Raises:
        FileNotFoundError: if *local_path* does not exist.
        pydantic.ValidationError: if the *global* file's ``[broker]`` or
            ``[logging]`` sections fail validation.
        tomllib.TOMLDecodeError: if either TOML file has a syntax error.
    """
    local_path = Path(local_path)
    if not local_path.exists():
        raise FileNotFoundError(f"Local config not found: {local_path}")

    global_cfg = load_global_config(global_path)
    global_raw: dict[str, Any] = global_cfg.model_dump()
    local_raw: dict[str, Any] = _load_toml(local_path)

    return _deep_merge(global_raw, local_raw)
