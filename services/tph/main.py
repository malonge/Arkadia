import time
import json
import logging

import pandas as pd
import redis
import smbus2
import bme280


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("tph")


def get_data_sample(n: int, r: int, bus: smbus2.SMBus, address: int, calibration_params: bme280.params) -> pd.DataFrame:
    """
    Get a sample of data from the BME280 sensor.

    Args:
        n: The number of samples to take.
        r: The time to wait between samples in seconds.

    Returns:
        A pandas DataFrame containing the data.
    """
    timestamps = []
    temperatures = []
    humidities = [] 
    pressures = []
    sensor_times = []

    for _ in range(n):
        sensor_start = time.time()
        data = bme280.sample(bus, address, calibration_params)
        sensor_times.append(time.time() - sensor_start)
        
        timestamps.append(data.timestamp)
        temperatures.append(data.temperature)
        humidities.append(data.humidity)
        pressures.append(data.pressure)
        time.sleep(r)

    df = pd.DataFrame({
        "timestamp": timestamps,
        "temperature": temperatures,
        "humidity": humidities,
        "pressure": pressures,
        "sensor_time": sensor_times
    })

    df = df.astype({
        "timestamp": "datetime64[ns]",
        "temperature": "float64",
        "humidity": "float64", 
        "pressure": "float64",
        "sensor_time": "float64"
    })

    return df


def is_valid_sample(sample_data: pd.DataFrame) -> bool:
    """
    Check if the sample data is valid.
    """
    if sample_data.empty:
        return False
    if sample_data.isnull().any().any():
        return False
    if sample_data['sensor_time'].std() > 0.01:
        return False
    return True


def connect_redis(retries=5, delay=1):
    for i in range(retries):
        try:
            cache = redis.Redis(host="redis", port=6379, db=0)
            cache.ping()
            logger.info("Connected to Redis")
            return cache
        except redis.ConnectionError:
            if i == retries - 1:
                raise
            logger.warning(f"Failed to connect to Redis, retrying in {delay} seconds...")
            time.sleep(delay)


def main():
    # BME280 initialization
    logger.info("Initializing BME280")
    port = 1
    address = 0x76
    bus = smbus2.SMBus(port)
    calibration_params = bme280.load_calibration_params(bus, address)
    logger.info(type(calibration_params))
    logger.info("BME280 initialized")

    # Redis initialization
    cache = connect_redis()

    while True:
        sample_data = get_data_sample(20, 0.1, bus, address, calibration_params)
        logger.info(f"Sampled data:\n{sample_data.describe()}")
        logger.info("")

        if is_valid_sample(sample_data):
            median_data = {
                'temperature': sample_data['temperature'].median(),
                'humidity': sample_data['humidity'].median(), 
                'pressure': sample_data['pressure'].median(),
                'timestamp': str(sample_data['timestamp'].max())
            }
            cache.set("tph", json.dumps(median_data))
        else:
            logger.warning("Invalid sample data. Skipping...")
            continue


if __name__ == "__main__":
    main()
