from datetime import datetime, timezone
import time

import pytest
import pandas as pd
import numpy as np
import redis
from unittest.mock import Mock, patch
import pytz

from main import get_data_sample, is_valid_sample, connect_redis


@pytest.fixture
def sample_df():
    return pd.DataFrame(
        {
            "timestamp": [datetime.now(pytz.utc).strftime("%Y-%m-%dT%H:%M:%SZ")] * 3,
            "temperature": [20.5, 20.6, 20.4],
            "humidity": [45.2, 45.3, 45.1],
            "pressure": [1013.2, 1013.3, 1013.1],
            "sensor_time": [0.001, 0.001, 0.001],
        }
    )


@pytest.fixture
def invalid_df():
    df = pd.DataFrame(
        {
            "timestamp": [datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")] * 3,
            "temperature": [20.5, np.nan, 20.4],
            "humidity": [45.2, 45.3, 45.1],
            "pressure": [1013.2, 1013.3, 1013.1],
            "sensor_time": [0.001, 0.1, 0.001],  # High variance
        }
    )
    return df


@patch("bme280_client.BME280Client.read_data")
def test_get_data_sample(mock_read_data):
    # Mock BME280 sample data with timestamp as float
    mock_data = {
        "timestamp": time.time(),  # Now using float timestamp
        "temperature": 20.5,
        "humidity": 45.0,
        "pressure": 1013.25,
    }

    mock_client = Mock()
    mock_client.read_data.return_value = mock_data

    df = get_data_sample(2, 0.1, mock_client)

    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert sorted(list(df.columns)) == sorted(
        [
            "timestamp",
            "temperature",
            "humidity",
            "pressure",
            "sensor_time",
        ]
    )
    # Timestamp should be string (object) since get_data_sample converts it
    assert df.dtypes["timestamp"] == "string"
    assert df.dtypes["temperature"] == "float64"
    assert df.dtypes["humidity"] == "float64"
    assert df.dtypes["pressure"] == "float64"
    assert df.dtypes["sensor_time"] == "float64"


def test_is_valid_sample(sample_df, invalid_df):
    assert is_valid_sample(sample_df)
    assert not is_valid_sample(pd.DataFrame())
    assert not is_valid_sample(invalid_df)

    # Test high sensor time variance
    high_variance_df = sample_df.copy()
    high_variance_df["sensor_time"] = [0.001, 0.1, 0.2]  # High variance
    assert not is_valid_sample(high_variance_df)


@patch("redis.Redis")
def test_connect_redis(mock_redis):
    mock_redis_instance = Mock()
    mock_redis.return_value = mock_redis_instance

    cache = connect_redis()
    assert cache == mock_redis_instance

    mock_redis.side_effect = [redis.ConnectionError(), mock_redis_instance]

    cache = connect_redis(retries=2, delay=0)
    assert cache == mock_redis_instance

    mock_redis.side_effect = redis.ConnectionError()
    with pytest.raises(redis.ConnectionError):
        connect_redis(retries=1, delay=0)
