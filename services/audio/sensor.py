"""INMP441 I2S microphone sensor driver.

Reads audio frames via sounddevice and provides pure-function helpers for
FFT spectrum analysis, octave-band aggregation, and RMS computation.

``sounddevice`` is imported lazily inside :meth:`AudioSensor.open` so that
the module can be imported and the pure computation functions can be used
in unit tests without a real audio device or ``sounddevice`` installed.

Public surface
--------------
- :class:`AudioSensor`               — hardware wrapper (open / read_frame / close)
- :func:`compute_stream_readings`    — pure FFT + EQ + RMS from a numpy array
- :func:`compute_summary_rms`        — energy-average RMS from accumulated frames
- :func:`make_window`                — build a named window array (Hann, Hamming, …)
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING

import numpy as np

from common.models import AudioReadings, AudioStreamReadings, EqBands, FftBins

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# dBFS value used when a signal is at or below the noise floor.
_DB_FLOOR = -120.0

# Supported window functions.
_WINDOW_FUNCS: dict[str, object] = {
    "hann": np.hanning,
    "hamming": np.hamming,
    "blackman": np.blackman,
    "bartlett": np.bartlett,
    "flat": np.ones,
}


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def make_window(name: str, size: int) -> np.ndarray:
    """Return a ``float32`` window array of length *size*.

    Args:
        name:  Window function name, one of ``"hann"``, ``"hamming"``,
               ``"blackman"``, ``"bartlett"``, or ``"flat"`` (rectangular).
        size:  Number of samples.

    Raises:
        ValueError: If *name* is not a recognised window function.
    """
    fn = _WINDOW_FUNCS.get(name.lower())
    if fn is None:
        raise ValueError(
            f"Unknown window function {name!r}. "
            f"Supported: {sorted(_WINDOW_FUNCS)}"
        )
    return fn(size).astype(np.float32)  # type: ignore[operator]


def compute_stream_readings(
    waveform: np.ndarray,
    *,
    sample_rate_hz: int,
    window_size: int,
    window: np.ndarray,
    freqs: np.ndarray,
    eq_bands_hz: list[float],
) -> AudioStreamReadings:
    """Compute a complete :class:`~common.models.AudioStreamReadings` from raw samples.

    This is the pure-function core of :meth:`AudioSensor.read_frame`.  It has
    no side-effects and does not touch hardware, making it directly testable.

    Args:
        waveform:       1-D ``float32`` array of *window_size* samples,
                        amplitude normalised to ``[-1.0, 1.0]``.
        sample_rate_hz: Sample rate used during capture (Hz).
        window_size:    Expected length of *waveform*.
        window:         Pre-computed window array of the same length.
        freqs:          Pre-computed FFT bin frequencies from
                        ``numpy.fft.rfftfreq(window_size, 1/sample_rate_hz)``.
        eq_bands_hz:    Centre frequencies of the octave bands to aggregate.

    Returns:
        A fully-populated :class:`~common.models.AudioStreamReadings` instance.
    """
    # --- FFT ---
    windowed = waveform * window
    spectrum = np.fft.rfft(windowed)

    # Normalise so a full-scale sine wave → 0 dBFS.
    # rfft returns N/2+1 values; dividing by N/2 converts to amplitude.
    mags = np.abs(spectrum) / (window_size / 2.0)
    mags_db = 20.0 * np.log10(np.clip(mags, 1e-10, None))

    fft_bins = FftBins(
        frequencies_hz=freqs.tolist(),
        magnitudes_db=mags_db.tolist(),
    )

    # --- EQ bands ---
    eq_bands = _aggregate_eq_bands(freqs, mags_db, eq_bands_hz)

    # --- RMS ---
    rms = float(np.sqrt(np.mean(waveform.astype(np.float64) ** 2)))
    db_level = 20.0 * math.log10(max(rms, 1e-10))

    return AudioStreamReadings(
        sample_rate_hz=sample_rate_hz,
        window_size=window_size,
        waveform=waveform.tolist(),
        fft_bins=fft_bins,
        eq_bands=eq_bands,
        rms_amplitude=rms,
        db_level=db_level,
    )


def compute_summary_rms(sum_sq_rms: float, n_frames: int) -> AudioReadings:
    """Compute a summary :class:`~common.models.AudioReadings` from accumulated frame data.

    Uses the energy-average formula:
    ``overall_rms = sqrt( Σ(rms_i²) / n_frames )``

    This preserves the correct RMS across the summary window because
    ``rms_i² = mean(x_i²)``, so the average of ``rms_i²`` equals the
    mean of all squared samples.

    Args:
        sum_sq_rms: Accumulated sum of ``rms_amplitude²`` for each frame.
        n_frames:   Number of frames accumulated.

    Returns:
        :class:`~common.models.AudioReadings` with the energy-averaged RMS and dBFS.
    """
    if n_frames == 0:
        return AudioReadings(rms_amplitude=0.0, db_level=_DB_FLOOR)

    rms = math.sqrt(sum_sq_rms / n_frames)
    db_level = 20.0 * math.log10(max(rms, 1e-10))
    return AudioReadings(rms_amplitude=rms, db_level=db_level)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _aggregate_eq_bands(
    freqs: np.ndarray,
    mags_db: np.ndarray,
    bands_hz: list[float],
) -> EqBands:
    """Average FFT bins into ISO 266 octave bands.

    Each band spans one octave: [centre / √2, centre × √2).  Magnitudes are
    converted to linear power before averaging, then back to dBFS so that the
    result reflects acoustic energy rather than arithmetic average of dB values.

    Bands that contain no FFT bins (possible at very low sample rates or very
    small window sizes) receive :data:`_DB_FLOOR`.
    """
    levels_db: list[float] = []
    sqrt2 = math.sqrt(2.0)

    for centre in bands_hz:
        low = centre / sqrt2
        high = centre * sqrt2
        mask = (freqs >= low) & (freqs < high)

        if mask.any():
            # Convert dB → linear power, average, convert back.
            linear = 10.0 ** (mags_db[mask] / 20.0)
            mean_linear = float(np.mean(linear))
            levels_db.append(20.0 * math.log10(max(mean_linear, 1e-10)))
        else:
            levels_db.append(_DB_FLOOR)

    return EqBands(bands_hz=bands_hz, levels_db=levels_db)


# ---------------------------------------------------------------------------
# Hardware wrapper
# ---------------------------------------------------------------------------


class AudioError(Exception):
    """Raised when an audio device operation fails."""


class AudioSensor:
    """Wraps a sounddevice InputStream for the INMP441 I2S microphone.

    Hardware is initialised in :meth:`open`.  Constructing the object does not
    contact any hardware, so tests can instantiate it freely.

    Example::

        sensor = AudioSensor(
            device_index=0,
            sample_rate_hz=16000,
            window_size=800,
            window_function="hann",
            eq_bands_hz=[63, 125, 250, 500, 1000, 2000, 4000, 8000],
        )
        sensor.open()
        readings = sensor.read_frame()   # blocks for ~50 ms
        sensor.close()
    """

    def __init__(
        self,
        *,
        device_index: int | None,
        sample_rate_hz: int,
        window_size: int,
        window_function: str,
        eq_bands_hz: list[float],
    ) -> None:
        self.device_index = device_index
        self.sample_rate_hz = sample_rate_hz
        self.window_size = window_size
        self.window_function = window_function
        self.eq_bands_hz = eq_bands_hz

        self._stream = None
        # Pre-compute window and frequency arrays so they are not rebuilt
        # on every call to read_frame().
        self._window = make_window(window_function, window_size)
        self._freqs = np.fft.rfftfreq(window_size, d=1.0 / sample_rate_hz)

    # ------------------------------------------------------------------
    # Hardware lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Open the sounddevice input stream.

        Raises :class:`AudioError` if the device cannot be opened.
        """
        try:
            import sounddevice as sd  # noqa: PLC0415 — lazy import for testability
        except Exception as exc:
            raise AudioError(f"sounddevice is not available: {exc}") from exc

        try:
            self._stream = sd.InputStream(
                device=self.device_index,
                channels=1,
                samplerate=self.sample_rate_hz,
                blocksize=self.window_size,
                dtype="float32",
            )
            self._stream.start()
        except Exception as exc:
            self._stream = None
            raise AudioError(f"Failed to open audio device {self.device_index}: {exc}") from exc

        logger.info(
            "Audio stream opened (device=%s, rate=%d Hz, window=%d samples)",
            self.device_index,
            self.sample_rate_hz,
            self.window_size,
            extra={"event": "audio_stream_opened"},
        )

    def read_frame(self) -> AudioStreamReadings:
        """Block until one audio frame is ready, then return computed readings.

        Each call blocks for approximately ``window_size / sample_rate_hz``
        seconds (e.g. 50 ms for window_size=800, sample_rate_hz=16 000).

        Raises :class:`AudioError` on device read failure.
        """
        if self._stream is None:
            raise AudioError("AudioSensor not opened; call open() first")

        try:
            data, overflowed = self._stream.read(self.window_size)
        except Exception as exc:
            raise AudioError(f"Audio read failed: {exc}") from exc

        if overflowed:
            logger.warning(
                "Audio input buffer overflowed; some samples may have been dropped",
                extra={"event": "audio_overflow"},
            )

        waveform = data.flatten().astype(np.float32)

        return compute_stream_readings(
            waveform,
            sample_rate_hz=self.sample_rate_hz,
            window_size=self.window_size,
            window=self._window,
            freqs=self._freqs,
            eq_bands_hz=self.eq_bands_hz,
        )

    def close(self) -> None:
        """Stop and release the audio stream."""
        if self._stream is not None:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            finally:
                self._stream = None
            logger.info("Audio stream closed", extra={"event": "audio_stream_closed"})
