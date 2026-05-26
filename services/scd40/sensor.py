"""SCD40 sensor driver — wraps adafruit-circuitpython-scd4x."""

from __future__ import annotations

import logging
import time

from common.i2c import I2CBase, I2CError

logger = logging.getLogger(__name__)

# The SCD40 produces a new measurement every 5 seconds.  Allow up to this
# many seconds for data_ready to become True before giving up.
_DATA_READY_TIMEOUT = 10.0


class SCD40Sensor(I2CBase):
    """Read CO₂, temperature, and humidity from an SCD40 over I2C.

    The SCD40 operates on a fixed 5-second internal measurement cycle.
    :meth:`read` blocks until a fresh measurement is available
    (``data_ready == True``), which may take up to 5 seconds.

    Call :meth:`open` at startup for fail-fast hardware initialisation.
    Hardware is otherwise initialised lazily on the first :meth:`read` call.

    Example::

        sensor = SCD40Sensor()
        sensor.open()
        data = sensor.read()   # blocks up to 5 s for first measurement
        # {"co2_ppm": 412.0, "temperature_c": 22.1, "humidity_pct": 48.3}
    """

    # The SCD40 has a single fixed I2C address.
    _FIXED_ADDRESS = 0x62

    def __init__(self, bus: int = 1, *, address: int = 0x62) -> None:
        super().__init__(bus=bus, address=address)
        self._scd4x = None

    # ------------------------------------------------------------------
    # Hardware lifecycle
    # ------------------------------------------------------------------

    def open(self) -> None:
        """Explicitly initialise hardware.  Raises :class:`~common.i2c.I2CError` on failure."""
        self._init_hardware()

    def _init_hardware(self) -> None:
        """Open the I2C bus, initialise the SCD4X device, and start periodic measurement.

        Always stops periodic measurement before starting it.  The SCD40 may
        already be running from a previous process session (e.g. after a service
        restart without a full power cycle).  Calling ``start_periodic_measurement``
        on a sensor that is already measuring causes the command to be silently
        rejected, leaving the sensor in an unexpected state.  Stopping first
        guarantees a clean baseline regardless of prior state.
        """
        try:
            import board  # type: ignore[import-untyped]
            import busio  # type: ignore[import-untyped]
            import adafruit_scd4x  # type: ignore[import-untyped]

            self._i2c = busio.I2C(board.SCL, board.SDA)
            self._scd4x = adafruit_scd4x.SCD4X(self._i2c)

            # Stop any in-progress measurement before starting fresh.
            # The SCD40 datasheet requires a 500 ms idle period between
            # stop and the next start command.
            try:
                self._scd4x.stop_periodic_measurement()
                time.sleep(0.6)
            except Exception:
                pass  # sensor was idle — not an error

            self._scd4x.start_periodic_measurement()
            logger.info(
                "SCD40 ready at I2C address 0x%02X (bus %d); periodic measurement started",
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
            raise I2CError(
                f"Failed to initialise SCD40 at 0x{self._address:02X} on bus {self._bus}: {exc}"
            ) from exc

    def close(self) -> None:
        """Stop periodic measurement and release hardware resources."""
        if self._scd4x is not None:
            try:
                self._scd4x.stop_periodic_measurement()
            except Exception:
                logger.exception("Error stopping SCD40 measurement", extra={"event": "sensor_error"})
            self._scd4x = None
        super().close()

    # ------------------------------------------------------------------
    # Sensor reading
    # ------------------------------------------------------------------

    def read(self) -> dict[str, float]:
        """Wait for the next SCD40 measurement and return it.

        Blocks until ``data_ready`` is ``True`` (up to ~5 s per cycle).

        Returns a dict with keys ``co2_ppm``, ``temperature_c``, and
        ``humidity_pct``.

        Raises :class:`~common.i2c.I2CError` if data does not become
        available within the timeout or on any hardware failure.
        """
        if self._scd4x is None:
            self._init_hardware()

        try:
            deadline = time.monotonic() + _DATA_READY_TIMEOUT
            while not self._scd4x.data_ready:
                if time.monotonic() >= deadline:
                    # Invalidate the device handle so the next read() call
                    # fully reinitialises the sensor (stop → start) rather
                    # than polling the same stuck device again.
                    self._scd4x = None
                    raise I2CError(
                        f"SCD40 data_ready timeout after {_DATA_READY_TIMEOUT:.0f}s"
                    )
                time.sleep(0.1)

            return {
                "co2_ppm": float(self._scd4x.CO2),
                "temperature_c": float(self._scd4x.temperature),
                "humidity_pct": float(self._scd4x.relative_humidity),
            }
        except I2CError:
            raise
        except Exception as exc:
            raise I2CError(f"SCD40 read failed: {exc}") from exc
