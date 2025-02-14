import pytest
import pandas as pd
import numpy as np
import redis
from datetime import datetime
from unittest.mock import Mock, patch

from main import get_data_sample, is_valid_sample, connect_redis

@pytest.fixture
def sample_df():
    return pd.DataFrame({
        "timestamp": [datetime.now()] * 3,
        "temperature": [20.5, 20.6, 20.4],
        "humidity": [45.2, 45.3, 45.1],
        "pressure": [1013.2, 1013.3, 1013.1],
        "sensor_time": [0.001, 0.001, 0.001]
    })

@pytest.fixture
def invalid_df():
    df = pd.DataFrame({
        "timestamp": [datetime.now()] * 3,
        "temperature": [20.5, np.nan, 20.4],
        "humidity": [45.2, 45.3, 45.1],
        "pressure": [1013.2, 1013.3, 1013.1],
        "sensor_time": [0.001, 0.1, 0.001]  # High variance
    })
    return df

@patch('bme280.sample')
def test_get_data_sample(mock_sample):
    # Mock BME280 sample data
    mock_data = Mock()
    mock_data.timestamp = datetime.now()
    mock_data.temperature = 20.5
    mock_data.humidity = 45.0
    mock_data.pressure = 1013.25
    mock_sample.return_value = mock_data

    # Test with n=2 samples and r=0.1s delay
    df = get_data_sample(2, 0.1, Mock(), Mock(), Mock())
    
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 2
    assert list(df.columns) == ["timestamp", "temperature", "humidity", "pressure", "sensor_time"]
    assert df.dtypes["timestamp"] == "datetime64[ns]"
    assert df.dtypes["temperature"] == "float64"
    assert df.dtypes["humidity"] == "float64"
    assert df.dtypes["pressure"] == "float64"
    assert df.dtypes["sensor_time"] == "float64"

def test_is_valid_sample(sample_df, invalid_df):
    # Test valid sample
    assert is_valid_sample(sample_df) == True
    
    # Test invalid cases
    assert is_valid_sample(pd.DataFrame()) == False  # Empty DataFrame
    assert is_valid_sample(invalid_df) == False  # Contains NaN
    
    # Test high sensor time variance
    high_variance_df = sample_df.copy()
    high_variance_df['sensor_time'] = [0.001, 0.1, 0.2]  # High variance
    assert is_valid_sample(high_variance_df) == False

@patch('redis.Redis')
def test_connect_redis(mock_redis):
    # Test successful connection
    mock_redis_instance = Mock()
    mock_redis.return_value = mock_redis_instance
    
    cache = connect_redis()
    assert cache == mock_redis_instance
    
    # Test failed connection with retry
    mock_redis.side_effect = [
        redis.ConnectionError(),
        mock_redis_instance
    ]
    
    cache = connect_redis(retries=2, delay=0)
    assert cache == mock_redis_instance
    
    # Test all retries failed
    mock_redis.side_effect = redis.ConnectionError()
    with pytest.raises(redis.ConnectionError):
        connect_redis(retries=1, delay=0)
