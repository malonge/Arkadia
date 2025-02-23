import smbus2
import time
import logging
from typing import Dict, Any, Tuple
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class CalibrationData:
    """BME280 calibration data"""

    dig_T1: int
    dig_T2: int
    dig_T3: int
    dig_P1: int
    dig_P2: int
    dig_P3: int
    dig_P4: int
    dig_P5: int
    dig_P6: int
    dig_P7: int
    dig_P8: int
    dig_P9: int
    dig_H1: int
    dig_H2: int
    dig_H3: int
    dig_H4: int
    dig_H5: int
    dig_H6: int


class BME280Client:
    """BME280 sensor client"""

    # BME280 registers
    CHIP_ID_REG = 0xD0
    RESET_REG = 0xE0
    CTRL_HUM_REG = 0xF2
    STATUS_REG = 0xF3
    CTRL_MEAS_REG = 0xF4
    CONFIG_REG = 0xF5
    DATA_REG = 0xF7
    CALIB_REG = 0x88
    CALIB_HUM_REG = 0xE1

    def __init__(self, port: int = 1, address: int = 0x76):
        """
        Initialize the BME280 sensor client.

        Args:
            port: The I2C bus port number
            address: The I2C device address
        """
        self.port = port
        self.address = address
        self.bus = smbus2.SMBus(port)
        self.calib = self._load_calibration()
        self._configure_sensor()
        logger.info(f"Initialized BME280 sensor on port {port} at address {address}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @staticmethod
    def _get_signed_16(msb: int, lsb: int) -> int:
        """Convert two bytes to signed 16-bit integer"""
        val = (msb << 8) | lsb
        return val - 65536 if val >= 32768 else val

    def _get_temperature_calibration(self, data: bytes) -> Tuple[int, int, int]:
        """Load temperature calibration data from the sensor"""
        dig_T1 = (data[1] << 8) | data[0]  # unsigned short
        dig_T2 = self._get_signed_16(data[3], data[2])  # signed short
        dig_T3 = self._get_signed_16(data[5], data[4])  # signed short
        return dig_T1, dig_T2, dig_T3

    def _get_pressure_calibration(
        self, data: bytes
    ) -> Tuple[int, int, int, int, int, int, int, int, int]:
        """Load pressure calibration data from the sensor"""
        dig_P1 = (data[7] << 8) | data[6]  # unsigned short
        dig_P2 = self._get_signed_16(data[9], data[8])  # signed short
        dig_P3 = self._get_signed_16(data[11], data[10])  # signed short
        dig_P4 = self._get_signed_16(data[13], data[12])  # signed short
        dig_P5 = self._get_signed_16(data[15], data[14])  # signed short
        dig_P6 = self._get_signed_16(data[17], data[16])  # signed short
        dig_P7 = self._get_signed_16(data[19], data[18])  # signed short
        dig_P8 = self._get_signed_16(data[21], data[20])  # signed short
        dig_P9 = self._get_signed_16(data[23], data[22])  # signed short
        return dig_P1, dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9

    def _get_humidity_calibration(
        self, cal1: bytes, cal2: bytes
    ) -> Tuple[int, int, int, int, int, int]:
        """Load humidity calibration data from the sensor"""
        dig_H1 = cal1[25]  # unsigned char from first calibration block
        dig_H2 = self._get_signed_16(cal2[1], cal2[0])  # signed short
        dig_H3 = cal2[2]  # unsigned char
        dig_H4 = (cal2[3] << 4) | (cal2[4] & 0x0F)  # signed short
        dig_H5 = (cal2[5] << 4) | (cal2[4] >> 4)  # signed short
        dig_H6 = cal2[6]  # signed char
        if dig_H6 > 127:
            dig_H6 -= 256
        return dig_H1, dig_H2, dig_H3, dig_H4, dig_H5, dig_H6

    def _load_calibration(self) -> CalibrationData:
        """Load calibration data from the sensor"""
        cal1 = self.bus.read_i2c_block_data(
            self.address, self.CALIB_REG, 26
        )  # Get all temp/pressure calibration
        cal2 = self.bus.read_i2c_block_data(
            self.address, self.CALIB_HUM_REG, 7
        )  # Get humidity calibration

        dig_T1, dig_T2, dig_T3 = self._get_temperature_calibration(cal1)
        dig_P1, dig_P2, dig_P3, dig_P4, dig_P5, dig_P6, dig_P7, dig_P8, dig_P9 = (
            self._get_pressure_calibration(cal1)
        )
        dig_H1, dig_H2, dig_H3, dig_H4, dig_H5, dig_H6 = self._get_humidity_calibration(cal1, cal2)

        return CalibrationData(
            dig_T1=dig_T1,
            dig_T2=dig_T2,
            dig_T3=dig_T3,
            dig_P1=dig_P1,
            dig_P2=dig_P2,
            dig_P3=dig_P3,
            dig_P4=dig_P4,
            dig_P5=dig_P5,
            dig_P6=dig_P6,
            dig_P7=dig_P7,
            dig_P8=dig_P8,
            dig_P9=dig_P9,
            dig_H1=dig_H1,
            dig_H2=dig_H2,
            dig_H3=dig_H3,
            dig_H4=dig_H4,
            dig_H5=dig_H5,
            dig_H6=dig_H6,
        )

    def _configure_sensor(self):
        """Configure the sensor for normal operation"""
        # Reset the device
        self.bus.write_byte_data(self.address, self.RESET_REG, 0xB6)
        time.sleep(0.1)

        # Set humidity oversampling to 1x
        self.bus.write_byte_data(self.address, self.CTRL_HUM_REG, 0x01)
        # Set temperature and pressure oversampling to 1x and mode to normal
        self.bus.write_byte_data(self.address, self.CTRL_MEAS_REG, 0x27)
        # Set standby time to 1s and filter off
        self.bus.write_byte_data(self.address, self.CONFIG_REG, 0x00)

    def _compensate_temperature(self, adc_T: int) -> float:
        """Compensate raw temperature reading using calibration data"""
        var1 = (adc_T / 16384.0 - self.calib.dig_T1 / 1024.0) * self.calib.dig_T2
        var2 = (
            (adc_T / 131072.0 - self.calib.dig_T1 / 8192.0)
            * (adc_T / 131072.0 - self.calib.dig_T1 / 8192.0)
            * self.calib.dig_T3
        )
        self.t_fine = var1 + var2
        return self.t_fine / 5120.0

    def _compensate_pressure(self, adc_P: int) -> float:
        """Compensate raw pressure reading using calibration data"""
        var1 = (self.t_fine / 2.0) - 64000.0
        var2 = var1 * var1 * self.calib.dig_P6 / 32768.0
        var2 = var2 + var1 * self.calib.dig_P5 * 2.0
        var2 = (var2 / 4.0) + (self.calib.dig_P4 * 65536.0)
        var1 = (self.calib.dig_P3 * var1 * var1 / 524288.0 + self.calib.dig_P2 * var1) / 524288.0
        var1 = (1.0 + var1 / 32768.0) * self.calib.dig_P1

        if var1 == 0:
            return 0

        p = 1048576.0 - adc_P
        p = (p - (var2 / 4096.0)) * 6250.0 / var1
        var1 = self.calib.dig_P9 * p * p / 2147483648.0
        var2 = p * self.calib.dig_P8 / 32768.0
        return p + (var1 + var2 + self.calib.dig_P7) / 16.0

    def _compensate_humidity(self, adc_H: int) -> float:
        """Compensate raw humidity reading using calibration data"""
        var_H = self.t_fine - 76800.0
        var_H = (adc_H - (self.calib.dig_H4 * 64.0 + self.calib.dig_H5 / 16384.0 * var_H)) * (
            self.calib.dig_H2
            / 65536.0
            * (
                1.0
                + self.calib.dig_H6
                / 67108864.0
                * var_H
                * (1.0 + self.calib.dig_H3 / 67108864.0 * var_H)
            )
        )
        var_H = var_H * (1.0 - self.calib.dig_H1 * var_H / 524288.0)

        if var_H > 100.0:
            var_H = 100.0
        elif var_H < 0.0:
            var_H = 0.0

        return var_H

    def read_data(self) -> Dict[str, Any]:
        """
        Read a single measurement from the BME280 sensor.

        Returns:
            Dictionary containing temperature (°C), pressure (hPa), and humidity (%)
        """
        try:
            data = self.bus.read_i2c_block_data(self.address, self.DATA_REG, 8)

            raw_pressure = (data[0] << 12) | (data[1] << 4) | (data[2] >> 4)
            raw_temperature = (data[3] << 12) | (data[4] << 4) | (data[5] >> 4)
            raw_humidity = (data[6] << 8) | data[7]

            # Compensate readings
            temperature = self._compensate_temperature(raw_temperature)
            pressure = self._compensate_pressure(raw_pressure) / 100.0  # Convert to hPa
            humidity = self._compensate_humidity(raw_humidity)

            return {
                "temperature": temperature,
                "pressure": pressure,
                "humidity": humidity,
                "timestamp": time.time(),
            }
        except Exception as e:
            logger.error(f"Error reading from BME280: {e}")
            raise

    def close(self):
        """Close the I2C bus connection"""
        self.bus.close()
