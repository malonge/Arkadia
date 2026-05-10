"""Pydantic models for all sensor payloads and the standard envelope."""

from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field, field_validator


# ---------------------------------------------------------------------------
# UTC timestamp helper
# ---------------------------------------------------------------------------


def _normalise_to_utc(v: datetime) -> datetime:
    """Normalise *v* to an aware UTC datetime.

    - Naive datetimes are assumed to already be in UTC and have ``tzinfo``
      attached without conversion.
    - Aware datetimes are converted to UTC regardless of their original zone.
    """
    if v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v.astimezone(timezone.utc)


class _UTCTimestampMixin(BaseModel):
    """Mixin that applies :func:`_normalise_to_utc` to the ``timestamp`` field.

    Inherit from this instead of repeating the ``ensure_utc`` validator in
    every payload class.  Pydantic v2 picks up validators defined on any class
    in the MRO, so the validator is active in all subclasses automatically.
    """

    timestamp: datetime

    @field_validator("timestamp")
    @classmethod
    def ensure_utc(cls, v: datetime) -> datetime:
        return _normalise_to_utc(v)


# ---------------------------------------------------------------------------
# Shared envelope sub-models
# ---------------------------------------------------------------------------


class Meta(BaseModel):
    """Aggregation metadata included in every payload."""

    sample_count: int = Field(..., ge=1, description="Number of samples taken")
    aggregation: str = Field(..., description="Aggregation method, e.g. 'median' or 'rms'")


class Diagnostics(BaseModel):
    """Optional service diagnostics block."""

    uptime_seconds: float = Field(..., ge=0)
    read_failures: int = Field(0, ge=0)


# ---------------------------------------------------------------------------
# Per-sensor readings models
# ---------------------------------------------------------------------------


class BME280Readings(BaseModel):
    """Temperature, humidity, and pressure from the BME280."""

    temperature_c: float = Field(..., description="Temperature in degrees Celsius")
    humidity_pct: float = Field(..., ge=0, le=100, description="Relative humidity in percent")
    pressure_hpa: float = Field(..., gt=0, description="Atmospheric pressure in hPa")


class SCD40Readings(BaseModel):
    """CO₂ concentration from the SCD40."""

    co2_ppm: float = Field(..., ge=0, description="CO₂ concentration in parts per million")
    temperature_c: float | None = Field(None, description="Temperature in degrees Celsius (if available)")
    humidity_pct: float | None = Field(None, ge=0, le=100, description="Relative humidity in percent (if available)")


class AudioReadings(BaseModel):
    """Ambient sound level from the INMP441 microphone."""

    rms_amplitude: float = Field(..., ge=0, description="RMS amplitude of the sample window")
    db_level: float = Field(..., description="Sound pressure level in dBFS")


# ---------------------------------------------------------------------------
# Standard envelope
# ---------------------------------------------------------------------------


class SensorPayload(_UTCTimestampMixin):
    """Standard envelope wrapping any sensor's readings."""

    schema_version: Literal[1] = 1
    sensor_id: str = Field(..., min_length=1)
    timestamp: datetime = Field(..., description="UTC ISO 8601 timestamp of the reading")
    readings: BME280Readings | SCD40Readings | AudioReadings
    meta: Meta
    diagnostics: Diagnostics | None = None


# ---------------------------------------------------------------------------
# Sensor-specific typed payloads (sensor_id is fixed per type)
# ---------------------------------------------------------------------------


class BME280Payload(_UTCTimestampMixin):
    """Fully-typed payload for the BME280 climate sensor."""

    schema_version: Literal[1] = 1
    sensor_id: str = Field("bme280", pattern=r"^bme280$")
    timestamp: datetime
    readings: BME280Readings
    meta: Meta
    diagnostics: Diagnostics | None = None


class SCD40Payload(_UTCTimestampMixin):
    """Fully-typed payload for the SCD40 CO₂ sensor."""

    schema_version: Literal[1] = 1
    sensor_id: str = Field("scd40", pattern=r"^scd40$")
    timestamp: datetime
    readings: SCD40Readings
    meta: Meta
    diagnostics: Diagnostics | None = None


class AudioPayload(_UTCTimestampMixin):
    """Fully-typed payload for the INMP441 audio sensor."""

    schema_version: Literal[1] = 1
    sensor_id: str = Field("inmp441", pattern=r"^inmp441$")
    timestamp: datetime
    readings: AudioReadings
    meta: Meta
    diagnostics: Diagnostics | None = None
