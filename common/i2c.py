"""I2C base class with bus initialisation, address config, and error handling."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class I2CError(OSError):
    """Raised when an I2C operation fails."""


class I2CBase:
    """Base class for I2C sensor drivers.

    Subclasses should override :meth:`read` to return a dict of measurement
    values.  The constructor performs bus initialisation and validates the
    address; failures raise :class:`I2CError` immediately so that systemd can
    restart the service.

    This class does **not** import ``board`` or ``busio`` at module level so
    that the shared library can be imported in test environments without
    hardware-specific dependencies installed.
    """

    def __init__(self, bus: int = 1, *, address: int) -> None:
        """Initialise the I2C bus and verify the device is present.

        Parameters
        ----------
        bus:
            I2C bus number (e.g. ``1`` for ``/dev/i2c-1``).
        address:
            7-bit I2C device address (keyword-only, required).  There is no
            sensible generic default — callers must always supply the device's
            actual address.  Valid range: ``0x08``–``0x77``.
        """
        self._bus = bus
        self._address = address
        self._i2c: Any = None
        self._device: Any = None

        self._validate_address(address)
        logger.info(
            "I2C bus %d address 0x%02X initialised",
            bus,
            address,
            extra={"event": "i2c_init"},
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _validate_address(address: int) -> None:
        """Raise :class:`I2CError` if *address* is not a valid 7-bit address."""
        if not (0x08 <= address <= 0x77):
            raise I2CError(
                f"I2C address 0x{address:02X} is outside the valid range "
                f"0x08–0x77 (reserved addresses excluded)"
            )

    def _init_hardware(self) -> None:
        """Initialise the CircuitPython I2C bus.

        This method is separated from ``__init__`` so that it can be called
        lazily (or mocked in tests).  It imports ``board`` and ``busio`` only
        when hardware access is actually needed.
        """
        try:
            import board  # type: ignore[import-untyped]
            import busio  # type: ignore[import-untyped]

            self._i2c = busio.I2C(board.SCL, board.SDA)
            logger.info(
                "Hardware I2C bus opened",
                extra={"event": "i2c_bus_open"},
            )
        except Exception as exc:
            raise I2CError(f"Failed to open I2C bus {self._bus}: {exc}") from exc

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def read(self) -> dict[str, float]:
        """Read a single sample from the sensor.

        Subclasses must override this method.  Returns a dict of measurement
        names to float values.

        Raises :class:`I2CError` on hardware failure.
        """
        raise NotImplementedError("Subclasses must implement read()")

    def close(self) -> None:
        """Release I2C resources."""
        if self._i2c is not None:
            try:
                self._i2c.deinit()
            except Exception:
                logger.exception("Error closing I2C bus", extra={"event": "i2c_close_error"})
            finally:
                self._i2c = None
                logger.info("I2C bus closed", extra={"event": "i2c_bus_close"})

    def __enter__(self) -> "I2CBase":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
