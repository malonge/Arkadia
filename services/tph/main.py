import smbus2
import bme280
import time


def c2f(c):
    return c * 9/5 + 32


# BME280 initialization
port = 1
address = 0x76  # or 0x77 depending on your sensor
bus = smbus2.SMBus(port)
calibration_params = bme280.load_calibration_params(bus, address)

while True:
    data = bme280.sample(bus, address, calibration_params)
    print(f"\nTemperature: {c2f(data.temperature):.1f}°F")
    print(f"Humidity: {data.humidity:.1f}%")
    print(f"Pressure: {data.pressure:.1f}hPa")
    
    time.sleep(2)  # Wait 2 seconds before next reading
