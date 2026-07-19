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


class StreamMeta(Meta):
    """Extended metadata for real-time audio stream frames.

    Adds ``window_function`` to the standard ``Meta`` fields so that
    consumers know how to interpret FFT magnitudes.
    """

    window_function: str = Field(
        "hann",
        description=(
            "Windowing function applied before FFT, e.g. 'hann', 'hamming', "
            "'blackman'.  Affects spectral leakage characteristics."
        ),
    )


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


class SGP40Readings(BaseModel):
    """VOC Index from the SGP40 gas sensor.

    The VOC Index is a processed integer on the Sensirion scale (1–500).
    100 represents typical indoor air; values below 100 indicate cleaner-
    than-average air, values above 100 indicate increasing VOC contamination.
    """

    voc_index: int = Field(
        ..., ge=0, le=500, description="VOC Index (Sensirion scale 1–500; 100 = average indoor air)"
    )


class AudioReadings(BaseModel):
    """Ambient sound level from the INMP441 microphone.

    Published in the periodic summary payload every 5 seconds.
    """

    rms_amplitude: float = Field(..., ge=0, description="RMS amplitude of the sample window")
    db_level: float = Field(..., description="Sound pressure level in dBFS")


# ---------------------------------------------------------------------------
# Real-time audio stream sub-models
# ---------------------------------------------------------------------------


class FftBins(BaseModel):
    """FFT frequency spectrum for a single audio frame.

    Contains N/2 bins spanning DC (0 Hz) to the Nyquist frequency
    (``sample_rate_hz`` / 2).  Bin spacing is ``sample_rate_hz`` /
    ``window_size`` Hz.  The DC bin (index 0) is included but is typically
    not rendered in visualizations.
    """

    frequencies_hz: list[float] = Field(
        ...,
        description="Centre frequency of each bin in Hz, from 0 to Nyquist",
    )
    magnitudes_db: list[float] = Field(
        ...,
        description=(
            "Magnitude of each bin in dBFS (0 dBFS = full-scale); "
            "length must equal len(frequencies_hz)"
        ),
    )


class EqBands(BaseModel):
    """Octave-band levels aggregated from the FFT for equalizer display.

    Default band centres follow the standard ISO 266 octave series:
    63, 125, 250, 500, 1000, 2000, 4000, 8000 Hz.  Each level is the
    mean power of all FFT bins whose centre frequency falls within the
    band's octave boundaries (lower = centre / sqrt(2),
    upper = centre * sqrt(2)).
    """

    bands_hz: list[float] = Field(
        ...,
        description="Centre frequency of each octave band in Hz",
    )
    levels_db: list[float] = Field(
        ...,
        description=(
            "Mean power level of each band in dBFS; "
            "length must equal len(bands_hz)"
        ),
    )


class AudioStreamReadings(BaseModel):
    """Real-time audio frame containing waveform, FFT spectrum, and EQ bands.

    One instance is published per captured window of audio.  A frame is
    self-contained: consumers may render either the time-domain waveform
    (amplitude vs. time) or the frequency-domain spectrum (magnitude vs.
    frequency) without buffering adjacent frames.
    """

    sample_rate_hz: int = Field(
        ..., gt=0, description="Sample rate of the audio capture in Hz"
    )
    window_size: int = Field(
        ..., gt=0, description="Number of samples in this frame"
    )
    waveform: list[float] = Field(
        ...,
        description=(
            "Time-domain amplitude samples normalised to [-1.0, 1.0]; "
            "length equals window_size"
        ),
    )
    fft_bins: FftBins = Field(
        ..., description="FFT spectrum computed from waveform via the configured window function"
    )
    eq_bands: EqBands = Field(
        ..., description="Octave-band summary for equalizer display"
    )
    rms_amplitude: float = Field(
        ..., ge=0, description="RMS amplitude of waveform, normalised to [0, 1]"
    )
    db_level: float = Field(
        ..., description="RMS level of this frame in dBFS"
    )


# ---------------------------------------------------------------------------
# Standard envelope
# ---------------------------------------------------------------------------


class SensorPayload(_UTCTimestampMixin):
    """Standard envelope wrapping any sensor's readings."""

    schema_version: Literal[1] = 1
    sensor_id: str = Field(..., min_length=1)
    timestamp: datetime = Field(..., description="UTC ISO 8601 timestamp of the reading")
    readings: BME280Readings | SCD40Readings | SGP40Readings | AudioReadings | AudioStreamReadings
    meta: Meta | StreamMeta
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


class SGP40Payload(_UTCTimestampMixin):
    """Fully-typed payload for the SGP40 VOC sensor."""

    schema_version: Literal[1] = 1
    sensor_id: str = Field("sgp40", pattern=r"^sgp40$")
    timestamp: datetime
    readings: SGP40Readings
    meta: Meta
    diagnostics: Diagnostics | None = None


class AudioPayload(_UTCTimestampMixin):
    """Fully-typed payload for the INMP441 audio sensor.

    Published to ``home/sensors/audio/inmp441`` with QoS 1 and retain=true
    on the configured summary interval (default: every 5 seconds).
    """

    schema_version: Literal[1] = 1
    sensor_id: str = Field("inmp441", pattern=r"^inmp441$")
    timestamp: datetime
    readings: AudioReadings
    meta: Meta
    diagnostics: Diagnostics | None = None


class AudioStreamPayload(_UTCTimestampMixin):
    """Real-time stream payload for the INMP441 audio sensor.

    Published to ``home/sensors/audio/inmp441/stream`` at the configured
    frame rate (default: 20 Hz / every 50 ms) with QoS 0 and retain=false.

    QoS 0 is intentional: dropping an occasional frame is acceptable for
    real-time visualization, and the reduced overhead keeps latency low.
    retain=false prevents new subscribers from receiving a stale audio frame
    that is no longer representative of the current sound environment.
    """

    schema_version: Literal[1] = 1
    sensor_id: str = Field("inmp441", pattern=r"^inmp441$")
    timestamp: datetime
    readings: AudioStreamReadings
    meta: StreamMeta
    diagnostics: Diagnostics | None = None
