"""SGP40 VOC sensor driver — wraps adafruit-circuitpython-sgp40."""

from __future__ import annotations

import logging

from common.i2c import I2CBase, I2CError

logger = logging.getLogger(__name__)

# Sensirion recommends calling measure_index() at ~1 s intervals.
# The algorithm builds an internal baseline from the running history;
# skipping cycles causes the baseline to drift and the index to become
# less accurate.  The service main loop enforces this cadence.
_SAMPLE_INTERVAL_S = 1.0


class SGP40Sensor(I2CBase):
    """Read the VOC Index from an SGP40 gas sensor over I2C.

    The SGP40 measures volatile organic compounds (VOCs) and reports a
    processed VOC Index on the Sensirion scale (1–500):

      - 1–100  : cleaner than average indoor air
      - 100    : typical indoor air (algorithm baseline)
      - 100–200: mildly elevated VOCs
      - 200–300: poor air quality (noticeable odours / contaminants)
      - 300–500: very poor / hazardous

    The Adafruit ``adafruit_sgp40.SGP40.measure_index()`` method runs the
    Sensirion VOC Algorithm internally.  It should be called every
    :data:`_SAMPLE_INTERVAL_S` seconds so the algorithm can maintain its
    exponential moving average baseline.

    Example::

        sensor = SGP40Sensor(address=0x59)
        sensor.open()
        data = sensor.read()   # {"voc_index": 97}
    """

    _FIXED_ADDRESS = 0x59

    def __init__(self, bus: int = 1, *, address: int = 0x59) -> None:
        super().__init__(bus=bus, address=address)
        self._sgp40 = None

    # ------------------------------------------------------------------
    # Hardware lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Explicitly initialise hardware.  Raises :class:`~common.i2c.I2CError` on failure."""
        self._init_hardware()

    def _init_hardware(self) -> None:
        """Open the I2C bus and initialise the SGP40 device."""
        try:
            import board  # type: ignore[import-untyped]
            import busio  # type: ignore[import-untyped]
            import adafruit_sgp40  # type: ignore[import-untyped]

            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._sgp40 = adafruit_sgp40.SGP40(self._i2c)
            logger.info(
                "SGP40 ready at I2C address 0x%02X (bus %d)",
                self._address,
                self._bus,
                extra={"event": "i2c_bus_open"},
            )
        except I2CError:
            raise
        except Exception as exc:
            if self._i2c is not None:
                try:
                    self._i2c.deinit()
                except Exception:
                    pass
                self._i2c = None
            self._sgp40 = None
            raise I2CError(
                f"Failed to initialise SGP40 at 0x{self._address:02X} on bus {self._bus}: {exc}"
            ) from exc

    def close(self) -> None:
        """Release hardware resources."""
        self._sgp40 = None
        super().close()

    # ------------------------------------------------------------------
    # Sensor reading
    # ------------------------------------------------------------------

    def read(self) -> dict[str, int]:
        """Return the current VOC Index.

        Calls the Sensirion VOC Algorithm via the Adafruit library.
        Should be called at ~1 s intervals for accurate baseline tracking.

        Returns a dict with key ``voc_index`` (int, 0–500).

        Raises :class:`~common.i2c.I2CError` on hardware failure.
        """
        if self._sgp40 is None:
            self._init_hardware()

        try:
            index = self._sgp40.measure_index()
            return {"voc_index": int(index)}
        except I2CError:
            raise
        except Exception as exc:
            raise I2CError(f"SGP40 read failed: {exc}") from exc
