"""BME280 sensor driver — wraps adafruit-circuitpython-bme280."""

from __future__ import annotations

import logging

from common.i2c import I2CBase, I2CError

logger = logging.getLogger(__name__)


class BME280Sensor(I2CBase):
    """Read temperature, humidity, and pressure from a BME280 over I2C.

    Hardware is initialised lazily on the first :meth:`read` call so that the
    module can be imported and the object constructed without hardware present
    (useful in tests).  Call :meth:`open` explicitly if you want to fail fast
    at startup rather than on the first poll cycle.

    Example::

        sensor = BME280Sensor(address=0x76)
        sensor.open()
        data = sensor.read()
        # {"temperature_c": 21.4, "humidity_pct": 55.2, "pressure_hpa": 1013.25}
    """

    def __init__(self, bus: int = 1, *, address: int = 0x76) -> None:
        super().__init__(bus=bus, address=address)
        self._bme280 = None

    # ------------------------------------------------------------------
    # Hardware lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Explicitly initialise hardware.  Raises :class:`~common.i2c.I2CError` on failure."""
        self._init_hardware()

    def _init_hardware(self) -> None:
        """Open the I2C bus and initialise the BME280 device object."""
        try:
            import board  # type: ignore[import-untyped]
            import busio  # type: ignore[import-untyped]
            import adafruit_bme280.basic as adafruit_bme280  # type: ignore[import-untyped]

            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._bme280 = adafruit_bme280.Adafruit_BME280_I2C(
                self._i2c, address=self._address
            )
            logger.info(
                "BME280 ready at I2C address 0x%02X (bus %d)",
                self._address,
                self._bus,
                extra={"event": "i2c_bus_open"},
            )
        except I2CError:
            raise
        except Exception as exc:
            # If the I2C bus was opened but the BME280 device init failed,
            # close the bus now so that a subsequent _init_hardware() call
            # does not open a second bus on top of the leaked first one.
            if self._i2c is not None:
                try:
                    self._i2c.deinit()
                except Exception:
                    pass
                self._i2c = None
            raise I2CError(
                f"Failed to initialise BME280 at 0x{self._address:02X} on bus {self._bus}: {exc}"
            ) from exc

    def close(self) -> None:
        """Release the BME280 device and the underlying I2C bus."""
        self._bme280 = None
        super().close()

    # ------------------------------------------------------------------
    # Sensor reading
    # ------------------------------------------------------------------

    def read(self) -> dict[str, float]:
        """Return one sample from the BME280.

        Returns a dict with keys ``temperature_c``, ``humidity_pct``, and
        ``pressure_hpa``.

        Hardware is initialised on the first call if :meth:`open` was not
        called explicitly.

        Raises :class:`~common.i2c.I2CError` on any hardware failure.
        """
        if self._bme280 is None:
            self._init_hardware()

        try:
            return {
                "temperature_c": float(self._bme280.temperature),
                "humidity_pct": float(self._bme280.relative_humidity),
                "pressure_hpa": float(self._bme280.pressure),
            }
        except Exception as exc:
            raise I2CError(f"BME280 read failed: {exc}") from exc
