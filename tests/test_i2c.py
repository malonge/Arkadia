"""Unit tests for common/i2c.py — no hardware required."""

import pytest

from common.i2c import I2CBase, I2CError


# ---------------------------------------------------------------------------
# Bug 2: address must be keyword-only and required (no default=0x00)
# ---------------------------------------------------------------------------


class TestI2CBaseAddressRequirement:
    def test_address_is_required(self):
        """I2CBase() without an address must raise TypeError, not I2CError."""
        with pytest.raises(TypeError):
            I2CBase()  # address not supplied

    def test_address_keyword_only(self):
        """address cannot be passed positionally."""
        with pytest.raises(TypeError):
            I2CBase(1, 0x76)  # second positional arg — keyword-only since Bug 2 fix

    def test_valid_address_accepted(self):
        base = I2CBase(address=0x76)
        assert base._address == 0x76

    def test_valid_address_with_bus(self):
        base = I2CBase(bus=1, address=0x76)
        assert base._bus == 1
        assert base._address == 0x76

    def test_default_bus_is_one(self):
        base = I2CBase(address=0x76)
        assert base._bus == 1


class TestI2CBaseAddressValidation:
    def test_address_too_low(self):
        with pytest.raises(I2CError, match="outside the valid range"):
            I2CBase(address=0x07)

    def test_address_zero(self):
        """0x00 (the former misleading default) must be rejected."""
        with pytest.raises(I2CError, match="outside the valid range"):
            I2CBase(address=0x00)

    def test_address_reserved_high(self):
        with pytest.raises(I2CError, match="outside the valid range"):
            I2CBase(address=0x78)

    def test_address_lower_boundary(self):
        base = I2CBase(address=0x08)
        assert base._address == 0x08

    def test_address_upper_boundary(self):
        base = I2CBase(address=0x77)
        assert base._address == 0x77


class TestI2CBaseReadNotImplemented:
    def test_read_raises(self):
        base = I2CBase(address=0x76)
        with pytest.raises(NotImplementedError):
            base.read()


class TestI2CBaseContextManager:
    def test_context_manager_no_hardware(self):
        """Context manager must work even without hardware (no _i2c to deinit)."""
        with I2CBase(address=0x76) as base:
            assert base._address == 0x76
        # close() should be a no-op when _i2c is None
        assert base._i2c is None


class TestI2CBaseAttributes:
    def test_no_device_attribute(self):
        """_device was removed as unused dead code; it must not exist on base."""
        base = I2CBase(address=0x76)
        assert not hasattr(base, "_device"), "_device is dead code and was removed"

    def test_i2c_starts_as_none(self):
        """_i2c must be None until _init_hardware() is called."""
        base = I2CBase(address=0x76)
        assert base._i2c is None
