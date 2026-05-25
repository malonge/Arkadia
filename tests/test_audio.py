"""Unit tests for the audio sensor service — no hardware required.

Strategy
--------
``sounddevice`` is not installed in the CI environment.  We inject a fake
module into ``sys.modules`` before importing ``sensor.py`` so that
``AudioSensor.open()`` and ``read_frame()`` resolve to our fake stream.

The pure computation functions (``compute_stream_readings``,
``compute_summary_rms``, ``make_window``) are tested directly without any
mocking by constructing numpy arrays of known content and verifying the
results analytically.

Hardware context
----------------
The INMP441 + googlevoicehat-soundcard driver always presents a *stereo*
48 kHz stream.  ``AudioSensor`` reads both channels and extracts the one
carrying signal (``channel=0`` for L/R=GND, ``channel=1`` for L/R=3V3).
Tests that exercise the hardware path return stereo fake data accordingly.

All tests are hardware-free and run on any platform with numpy available.
"""

from __future__ import annotations

import json
import math
import sys
import types
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import numpy as np
import pytest
from pydantic import ValidationError

# ---------------------------------------------------------------------------
# Ensure services/audio is on sys.path so sensor.py is importable.
# ---------------------------------------------------------------------------

SERVICE_DIR = Path(__file__).resolve().parent.parent / "services" / "audio"

_OTHER_SERVICE_DIRS = [
    Path(__file__).resolve().parent.parent / "services" / "bme280",
    Path(__file__).resolve().parent.parent / "services" / "scd40",
]


def _activate_service_path() -> None:
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
# Shared test fixtures
# ---------------------------------------------------------------------------

# Match the real hardware config: 48 kHz stereo, 2400-sample window.
SAMPLE_RATE = 48000
WINDOW_SIZE = 2400
CHANNELS = 2
CHANNEL = 0   # left channel carries signal (L/R = GND)
EQ_BANDS = [63.0, 125.0, 250.0, 500.0, 1000.0, 2000.0, 4000.0, 8000.0]


def _make_window_and_freqs(size: int = WINDOW_SIZE, rate: int = SAMPLE_RATE):
    """Return (window, freqs) arrays matching sensor defaults."""
    from sensor import make_window
    window = make_window("hann", size)
    freqs = np.fft.rfftfreq(size, d=1.0 / rate)
    return window, freqs


def _sine_wave(frequency_hz: float, amplitude: float = 0.5,
               n_samples: int = WINDOW_SIZE,
               sample_rate: int = SAMPLE_RATE) -> np.ndarray:
    """Return a single-frequency float32 sine wave (mono)."""
    t = np.arange(n_samples) / sample_rate
    return (amplitude * np.sin(2 * np.pi * frequency_hz * t)).astype(np.float32)


def _stereo_from_mono(mono: np.ndarray, channel: int = CHANNEL,
                      n_channels: int = CHANNELS) -> np.ndarray:
    """Pack a mono array into a (n_samples, n_channels) stereo array."""
    stereo = np.zeros((len(mono), n_channels), dtype=np.float32)
    stereo[:, channel] = mono
    return stereo


# ---------------------------------------------------------------------------
# make_window tests
# ---------------------------------------------------------------------------

class TestMakeWindow:
    def setup_method(self):
        _activate_service_path()

    def test_hann_shape(self):
        from sensor import make_window
        w = make_window("hann", WINDOW_SIZE)
        assert len(w) == WINDOW_SIZE

    def test_hann_dtype(self):
        from sensor import make_window
        w = make_window("hann", WINDOW_SIZE)
        assert w.dtype == np.float32

    def test_hann_endpoints_near_zero(self):
        from sensor import make_window
        w = make_window("hann", WINDOW_SIZE)
        assert abs(w[0]) < 1e-6
        assert abs(w[-1]) < 1e-3

    def test_hamming_peak_above_zero(self):
        from sensor import make_window
        w = make_window("hamming", 100)
        assert w.max() > 0.9

    def test_flat_window_is_all_ones(self):
        from sensor import make_window
        w = make_window("flat", 64)
        np.testing.assert_allclose(w, np.ones(64, dtype=np.float32))

    def test_unknown_window_raises(self):
        from sensor import make_window
        with pytest.raises(ValueError, match="Unknown window function"):
            make_window("kaiser", 64)

    def test_case_insensitive(self):
        from sensor import make_window
        w1 = make_window("Hann", 64)
        w2 = make_window("hann", 64)
        np.testing.assert_array_equal(w1, w2)


# ---------------------------------------------------------------------------
# compute_stream_readings tests
# ---------------------------------------------------------------------------

class TestComputeStreamReadings:
    def setup_method(self):
        _activate_service_path()

    def _compute(self, waveform: np.ndarray) -> object:
        from sensor import compute_stream_readings
        window, freqs = _make_window_and_freqs()
        return compute_stream_readings(
            waveform,
            sample_rate_hz=SAMPLE_RATE,
            window_size=WINDOW_SIZE,
            window=window,
            freqs=freqs,
            eq_bands_hz=EQ_BANDS,
        )

    def test_returns_correct_window_size(self):
        rdg = self._compute(_sine_wave(1000.0))
        assert rdg.window_size == WINDOW_SIZE

    def test_returns_correct_sample_rate(self):
        rdg = self._compute(_sine_wave(1000.0))
        assert rdg.sample_rate_hz == SAMPLE_RATE

    def test_waveform_passthrough(self):
        """The original waveform samples must be preserved exactly."""
        wave = _sine_wave(500.0)
        rdg = self._compute(wave)
        assert len(rdg.waveform) == WINDOW_SIZE
        np.testing.assert_allclose(rdg.waveform, wave, atol=1e-6)

    def test_fft_bins_length(self):
        """rfft of N-point real signal → N/2+1 bins."""
        rdg = self._compute(_sine_wave(1000.0))
        expected_bins = WINDOW_SIZE // 2 + 1
        assert len(rdg.fft_bins.frequencies_hz) == expected_bins
        assert len(rdg.fft_bins.magnitudes_db) == expected_bins

    def test_fft_frequency_range(self):
        """Bins must span [0, Nyquist] Hz."""
        rdg = self._compute(_sine_wave(1000.0))
        assert rdg.fft_bins.frequencies_hz[0] == pytest.approx(0.0)
        assert rdg.fft_bins.frequencies_hz[-1] == pytest.approx(SAMPLE_RATE / 2)

    def test_fft_peak_at_sine_frequency(self):
        """The FFT magnitude peak should fall at the input sine frequency."""
        freq = 1000.0
        rdg = self._compute(_sine_wave(freq, amplitude=0.8))
        mags = np.array(rdg.fft_bins.magnitudes_db)
        peak_idx = np.argmax(mags[1:]) + 1
        peak_freq = rdg.fft_bins.frequencies_hz[peak_idx]
        bin_width = SAMPLE_RATE / WINDOW_SIZE
        assert abs(peak_freq - freq) <= bin_width

    def test_silence_gives_db_floor(self):
        """A silent waveform should produce very low dBFS values."""
        rdg = self._compute(np.zeros(WINDOW_SIZE, dtype=np.float32))
        assert rdg.db_level < -60.0
        assert all(m < -60.0 for m in rdg.fft_bins.magnitudes_db)

    def test_full_scale_sine_near_zero_dbfs(self):
        """A full-scale sine (amplitude=1.0) should be close to 0 dBFS."""
        rdg = self._compute(_sine_wave(1000.0, amplitude=1.0))
        mags = np.array(rdg.fft_bins.magnitudes_db)
        peak_db = float(np.max(mags[1:]))
        assert -10.0 < peak_db <= 3.0

    def test_rms_amplitude_range(self):
        """RMS of a unit sine is 1/√2 ≈ 0.707."""
        rdg = self._compute(_sine_wave(1000.0, amplitude=1.0))
        assert rdg.rms_amplitude == pytest.approx(1.0 / math.sqrt(2), rel=0.05)

    def test_rms_amplitude_non_negative(self):
        rdg = self._compute(_sine_wave(500.0))
        assert rdg.rms_amplitude >= 0.0

    def test_eq_bands_count(self):
        rdg = self._compute(_sine_wave(1000.0))
        assert len(rdg.eq_bands.bands_hz) == len(EQ_BANDS)
        assert len(rdg.eq_bands.levels_db) == len(EQ_BANDS)

    def test_eq_band_centres_preserved(self):
        rdg = self._compute(_sine_wave(1000.0))
        assert rdg.eq_bands.bands_hz == pytest.approx(EQ_BANDS)

    def test_eq_1khz_band_elevated_for_1khz_sine(self):
        """The 1 kHz band should be the loudest for a 1 kHz sine input."""
        rdg = self._compute(_sine_wave(1000.0, amplitude=0.5))
        idx_1k = EQ_BANDS.index(1000.0)
        level_1k = rdg.eq_bands.levels_db[idx_1k]
        for i, lvl in enumerate(rdg.eq_bands.levels_db):
            if i != idx_1k:
                assert level_1k > lvl, (
                    f"1 kHz band ({level_1k:.1f} dB) should be louder than "
                    f"band {EQ_BANDS[i]} Hz ({lvl:.1f} dB)"
                )

    def test_db_level_consistent_with_rms(self):
        """db_level must equal 20 * log10(rms_amplitude) (within float precision)."""
        rdg = self._compute(_sine_wave(440.0, amplitude=0.3))
        expected_db = 20.0 * math.log10(rdg.rms_amplitude)
        assert rdg.db_level == pytest.approx(expected_db, abs=0.01)


# ---------------------------------------------------------------------------
# compute_summary_rms tests
# ---------------------------------------------------------------------------

class TestComputeSummaryRms:
    def setup_method(self):
        _activate_service_path()

    def test_zero_frames_returns_silence(self):
        from sensor import compute_summary_rms
        rdg = compute_summary_rms(sum_sq_rms=0.0, n_frames=0)
        assert rdg.rms_amplitude == 0.0
        assert rdg.db_level < -100.0

    def test_single_frame(self):
        from sensor import compute_summary_rms
        rms = 0.1
        rdg = compute_summary_rms(sum_sq_rms=rms**2, n_frames=1)
        assert rdg.rms_amplitude == pytest.approx(rms, rel=1e-6)

    def test_constant_frames_match_single(self):
        """N identical frames should give the same RMS as one frame."""
        from sensor import compute_summary_rms
        rms = 0.25
        n = 100
        rdg = compute_summary_rms(sum_sq_rms=rms**2 * n, n_frames=n)
        assert rdg.rms_amplitude == pytest.approx(rms, rel=1e-6)

    def test_db_level_matches_rms(self):
        from sensor import compute_summary_rms
        rms = 0.05
        rdg = compute_summary_rms(sum_sq_rms=rms**2, n_frames=1)
        expected_db = 20.0 * math.log10(rms)
        assert rdg.db_level == pytest.approx(expected_db, abs=0.01)

    def test_energy_average_correct(self):
        """Energy-average of two different RMS values."""
        from sensor import compute_summary_rms
        rms_a, rms_b = 0.1, 0.3
        sum_sq = rms_a**2 + rms_b**2
        rdg = compute_summary_rms(sum_sq_rms=sum_sq, n_frames=2)
        expected = math.sqrt((rms_a**2 + rms_b**2) / 2)
        assert rdg.rms_amplitude == pytest.approx(expected, rel=1e-6)

    def test_result_type(self):
        from sensor import compute_summary_rms
        from common.models import AudioReadings
        rdg = compute_summary_rms(sum_sq_rms=0.01, n_frames=1)
        assert isinstance(rdg, AudioReadings)


# ---------------------------------------------------------------------------
# AudioSensor hardware wrapper tests (sounddevice mocked)
# ---------------------------------------------------------------------------

def _make_fake_sounddevice(mono_waveform: np.ndarray | None = None,
                            n_channels: int = CHANNELS,
                            signal_channel: int = CHANNEL):
    """Inject a fake sounddevice module returning stereo data."""
    if mono_waveform is None:
        mono_waveform = np.zeros(WINDOW_SIZE, dtype=np.float32)

    stereo = _stereo_from_mono(mono_waveform, channel=signal_channel,
                                n_channels=n_channels)

    fake_sd = types.ModuleType("sounddevice")
    fake_stream = MagicMock()
    fake_stream.read.return_value = (stereo, False)
    fake_stream.start = MagicMock()
    fake_stream.stop = MagicMock()
    fake_stream.close = MagicMock()
    fake_sd.InputStream = MagicMock(return_value=fake_stream)

    sys.modules["sounddevice"] = fake_sd
    return fake_sd, fake_stream


def _remove_fake_sounddevice():
    sys.modules.pop("sounddevice", None)


def _default_sensor_kwargs(**overrides):
    """Return default AudioSensor constructor kwargs (matching real config)."""
    defaults = dict(
        device="mic_sv",
        sample_rate_hz=SAMPLE_RATE,
        channels=CHANNELS,
        channel=CHANNEL,
        window_size=WINDOW_SIZE,
        window_function="hann",
        eq_bands_hz=EQ_BANDS,
    )
    defaults.update(overrides)
    return defaults


class TestAudioSensorConstruction:
    def setup_method(self):
        _activate_service_path()

    def test_construction_does_not_touch_hardware(self):
        """Creating AudioSensor must not import sounddevice."""
        _remove_fake_sounddevice()
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        assert s._stream is None

    def test_window_precomputed(self):
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        assert len(s._window) == WINDOW_SIZE

    def test_freqs_precomputed(self):
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        assert len(s._freqs) == WINDOW_SIZE // 2 + 1

    def test_string_device_stored(self):
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs(device="mic_sv"))
        assert s.device == "mic_sv"

    def test_int_device_stored(self):
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs(device=0))
        assert s.device == 0


class TestAudioSensorOpen:
    def setup_method(self):
        _activate_service_path()
        _remove_fake_sounddevice()

    def teardown_method(self):
        _remove_fake_sounddevice()
        sys.modules.pop("sensor", None)

    def test_open_starts_stream(self):
        fake_sd, fake_stream = _make_fake_sounddevice()
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        s.open()
        fake_sd.InputStream.assert_called_once()
        fake_stream.start.assert_called_once()
        assert s._stream is not None

    def test_open_passes_correct_params(self):
        fake_sd, _ = _make_fake_sounddevice()
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs(device="mic_sv"))
        s.open()
        call_kwargs = fake_sd.InputStream.call_args.kwargs
        assert call_kwargs["device"] == "mic_sv"
        assert call_kwargs["samplerate"] == SAMPLE_RATE
        assert call_kwargs["blocksize"] == WINDOW_SIZE
        assert call_kwargs["channels"] == CHANNELS
        assert call_kwargs["dtype"] == "float32"

    def test_open_missing_sounddevice_raises_audio_error(self):
        from sensor import AudioError, AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        with pytest.raises(AudioError, match="sounddevice"):
            s.open()

    def test_open_device_failure_raises_audio_error(self):
        fake_sd = types.ModuleType("sounddevice")
        fake_sd.InputStream = MagicMock(side_effect=OSError("no device"))
        sys.modules["sounddevice"] = fake_sd
        from sensor import AudioError, AudioSensor
        s = AudioSensor(**_default_sensor_kwargs(device="bad_dev"))
        with pytest.raises(AudioError, match="Failed to open audio device"):
            s.open()

    def test_open_device_failure_leaves_stream_none(self):
        fake_sd = types.ModuleType("sounddevice")
        fake_sd.InputStream = MagicMock(side_effect=OSError("boom"))
        sys.modules["sounddevice"] = fake_sd
        from sensor import AudioError, AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        with pytest.raises(AudioError):
            s.open()
        assert s._stream is None


class TestAudioSensorReadFrame:
    def setup_method(self):
        _activate_service_path()
        _remove_fake_sounddevice()

    def teardown_method(self):
        _remove_fake_sounddevice()
        sys.modules.pop("sensor", None)

    def _open_sensor(self, mono_waveform: np.ndarray):
        fake_sd, fake_stream = _make_fake_sounddevice(mono_waveform)
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        s.open()
        return s, fake_stream

    def test_read_frame_returns_stream_readings(self):
        from common.models import AudioStreamReadings
        wave = _sine_wave(1000.0)
        s, _ = self._open_sensor(wave)
        rdg = s.read_frame()
        assert isinstance(rdg, AudioStreamReadings)

    def test_read_frame_extracts_correct_channel(self):
        """Signal on channel 0 must appear in waveform; channel 1 must be silent."""
        wave = _sine_wave(500.0, amplitude=0.4)
        s, _ = self._open_sensor(wave)  # signal on CHANNEL=0
        rdg = s.read_frame()
        np.testing.assert_allclose(rdg.waveform, wave, atol=1e-6)

    def test_read_frame_wrong_channel_gives_silence(self):
        """If signal is on channel 1 but we read channel 0, waveform should be zeros."""
        wave = _sine_wave(500.0, amplitude=0.4)
        # Put signal on channel 1, sensor reads channel 0
        stereo = _stereo_from_mono(wave, channel=1)
        fake_sd = types.ModuleType("sounddevice")
        fake_stream = MagicMock()
        fake_stream.read.return_value = (stereo, False)
        fake_stream.start = MagicMock()
        fake_sd.InputStream = MagicMock(return_value=fake_stream)
        sys.modules["sounddevice"] = fake_sd
        from sensor import AudioSensor
        s = AudioSensor(**_default_sensor_kwargs(channel=0))
        s.open()
        rdg = s.read_frame()
        # Channel 0 is zeros, so waveform should be flat
        assert rdg.rms_amplitude < 1e-6

    def test_read_frame_without_open_raises(self):
        from sensor import AudioError, AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        with pytest.raises(AudioError, match="not opened"):
            s.read_frame()

    def test_read_failure_raises_audio_error(self):
        fake_sd = types.ModuleType("sounddevice")
        fake_stream = MagicMock()
        fake_stream.start = MagicMock()
        fake_stream.read.side_effect = OSError("device disconnected")
        fake_sd.InputStream = MagicMock(return_value=fake_stream)
        sys.modules["sounddevice"] = fake_sd
        from sensor import AudioError, AudioSensor
        s = AudioSensor(**_default_sensor_kwargs())
        s.open()
        with pytest.raises(AudioError, match="Audio read failed"):
            s.read_frame()

    def test_close_stops_stream(self):
        wave = np.zeros(WINDOW_SIZE, dtype=np.float32)
        s, fake_stream = self._open_sensor(wave)
        s.close()
        fake_stream.stop.assert_called_once()
        fake_stream.close.assert_called_once()
        assert s._stream is None

    def test_close_idempotent(self):
        wave = np.zeros(WINDOW_SIZE, dtype=np.float32)
        s, _ = self._open_sensor(wave)
        s.close()
        s.close()  # second call must not raise


# ---------------------------------------------------------------------------
# Payload model tests
# ---------------------------------------------------------------------------

class TestAudioStreamPayloadBuilding:
    def setup_method(self):
        _activate_service_path()

    def _make_payload(self):
        from sensor import compute_stream_readings, make_window
        from common.models import AudioStreamPayload, Diagnostics, StreamMeta

        wave = _sine_wave(1000.0, amplitude=0.5)
        window = make_window("hann", WINDOW_SIZE)
        freqs = np.fft.rfftfreq(WINDOW_SIZE, d=1.0 / SAMPLE_RATE)
        readings = compute_stream_readings(
            wave,
            sample_rate_hz=SAMPLE_RATE,
            window_size=WINDOW_SIZE,
            window=window,
            freqs=freqs,
            eq_bands_hz=EQ_BANDS,
        )
        return AudioStreamPayload(
            sensor_id="inmp441",
            timestamp=datetime(2026, 5, 24, 18, 0, 0, tzinfo=timezone.utc),
            readings=readings,
            meta=StreamMeta(
                sample_count=WINDOW_SIZE,
                aggregation="fft",
                window_function="hann",
            ),
            diagnostics=Diagnostics(uptime_seconds=60.0, read_failures=0),
        )

    def test_valid_payload(self):
        p = self._make_payload()
        assert p.sensor_id == "inmp441"
        assert p.meta.window_function == "hann"

    def test_json_roundtrip(self):
        from common.models import AudioStreamPayload
        p = self._make_payload()
        restored = AudioStreamPayload.model_validate_json(p.model_dump_json())
        assert restored.readings.db_level == pytest.approx(p.readings.db_level)
        assert restored.readings.fft_bins.frequencies_hz == pytest.approx(
            p.readings.fft_bins.frequencies_hz, rel=1e-5
        )

    def test_schema_version(self):
        p = self._make_payload()
        data = json.loads(p.model_dump_json())
        assert data["schema_version"] == 1

    def test_timestamp_utc_normalised(self):
        p = self._make_payload()
        assert p.timestamp.tzinfo is not None
        assert p.timestamp.utcoffset().total_seconds() == 0

    def test_wrong_sensor_id_rejected(self):
        from common.models import AudioStreamPayload, AudioStreamReadings, EqBands, FftBins, StreamMeta
        with pytest.raises(ValidationError):
            AudioStreamPayload(
                sensor_id="wrong",
                timestamp=datetime(2026, 5, 24, tzinfo=timezone.utc),
                readings=AudioStreamReadings(
                    sample_rate_hz=SAMPLE_RATE,
                    window_size=4,
                    waveform=[0.0, 0.0, 0.0, 0.0],
                    fft_bins=FftBins(frequencies_hz=[0.0, 4000.0], magnitudes_db=[-80.0, -80.0]),
                    eq_bands=EqBands(bands_hz=[1000.0], levels_db=[-40.0]),
                    rms_amplitude=0.0,
                    db_level=-120.0,
                ),
                meta=StreamMeta(sample_count=4, aggregation="fft"),
            )

    def test_negative_rms_rejected(self):
        from common.models import AudioStreamReadings
        with pytest.raises(ValidationError):
            AudioStreamReadings(
                sample_rate_hz=SAMPLE_RATE,
                window_size=4,
                waveform=[0.0] * 4,
                fft_bins={"frequencies_hz": [0.0], "magnitudes_db": [-60.0]},
                eq_bands={"bands_hz": [1000.0], "levels_db": [-40.0]},
                rms_amplitude=-0.1,
                db_level=-60.0,
            )


class TestAudioSummaryPayloadBuilding:
    def test_valid_summary_payload(self):
        from sensor import compute_summary_rms
        from common.models import AudioPayload, Diagnostics, Meta

        rdg = compute_summary_rms(sum_sq_rms=0.01, n_frames=100)
        p = AudioPayload(
            sensor_id="inmp441",
            timestamp=datetime(2026, 5, 24, 18, 0, 0, tzinfo=timezone.utc),
            readings=rdg,
            meta=Meta(sample_count=100 * WINDOW_SIZE, aggregation="rms"),
            diagnostics=Diagnostics(uptime_seconds=300.0, read_failures=0),
        )
        assert p.sensor_id == "inmp441"
        assert p.meta.aggregation == "rms"

    def test_summary_json_roundtrip(self):
        from sensor import compute_summary_rms
        from common.models import AudioPayload, Meta

        rdg = compute_summary_rms(sum_sq_rms=0.04, n_frames=50)
        p = AudioPayload(
            sensor_id="inmp441",
            timestamp=datetime(2026, 5, 24, tzinfo=timezone.utc),
            readings=rdg,
            meta=Meta(sample_count=50 * WINDOW_SIZE, aggregation="rms"),
        )
        restored = AudioPayload.model_validate_json(p.model_dump_json())
        assert restored.readings.rms_amplitude == pytest.approx(
            p.readings.rms_amplitude, rel=1e-6
        )


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

class TestAudioConfig:
    def test_config_loads_without_error(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["sensor"]["sample_rate_hz"] == 48000
        assert cfg["sensor"]["window_size"] == 2400
        assert cfg["sensor"]["channels"] == 2
        assert cfg["sensor"]["channel"] == 0
        assert cfg["sensor"]["window_function"] == "hann"
        assert cfg["sensor"]["device"] == 0
        assert cfg["mqtt"]["stream_topic"] == "home/sensors/audio/inmp441/stream"
        assert cfg["mqtt"]["summary_topic"] == "home/sensors/audio/inmp441"

    def test_global_broker_defaults_merged(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["broker"]["host"] == "localhost"
        assert cfg["broker"]["port"] == 1883

    def test_eq_bands_list(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        bands = cfg["sensor"]["eq_bands_hz"]
        assert len(bands) == 8
        assert bands[0] == 63
        assert bands[-1] == 8000

    def test_summary_interval(self):
        from common.config import load_config
        cfg = load_config(SERVICE_DIR / "config.toml")
        assert cfg["sensor"]["summary_interval_seconds"] == 5

    def test_stream_topic_no_retain(self):
        """Config must not set retain=true on the stream topic."""
        import tomllib
        config_path = SERVICE_DIR / "config.toml"
        with config_path.open("rb") as fh:
            raw = tomllib.load(fh)
        assert "retain" not in raw.get("mqtt", {}), (
            "stream retain must not be set to true in config"
        )
