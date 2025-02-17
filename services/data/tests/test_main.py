import json

import pytest
from fastapi.testclient import TestClient
from redis.asyncio import Redis
from pytest_asyncio import fixture

from main import app, get_redis

# Test data
SAMPLE_TPH_DATA = {
    "temperature": 21.5,
    "pressure": 1013.25,
    "humidity": 45.7,
    "timestamp": "2024-01-01T12:00:00"
}

@pytest.fixture
def redis_mock(mocker):
    """Fixture that provides a mock Redis client"""
    mock = mocker.AsyncMock(spec=Redis)
    
    # Create a default AsyncMock for ping and get
    mock.ping = mocker.AsyncMock(return_value=True)
    mock.get = mocker.AsyncMock()
    
    async def override_get_redis():
        return mock
    
    app.dependency_overrides[get_redis] = override_get_redis
    return mock

@pytest.fixture
def client():
    """Fixture that provides a FastAPI test client"""
    return TestClient(app)

@pytest.fixture(autouse=True)
def cleanup():
    """Cleanup fixture to reset dependency overrides after each test"""
    yield
    app.dependency_overrides.clear()

@pytest.mark.asyncio
class TestHealthEndpoint:
    async def test_health_check_success(self, client, redis_mock):
        """Test health check endpoint when Redis is healthy"""
        redis_mock.ping.return_value = True
        
        response = client.get("/health")
        
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}
        redis_mock.ping.assert_called_once()

    async def test_health_check_failure(self, client, redis_mock):
        """Test health check endpoint when Redis is unhealthy"""
        redis_mock.ping.side_effect = Exception("Redis connection failed")
        
        response = client.get("/health")
        
        assert response.status_code == 503
        assert response.json() == {"detail": "Service unhealthy"}
        redis_mock.ping.assert_called_once()

@pytest.mark.asyncio
class TestTPHEndpoint:
    async def test_get_tph_data_success(self, client, redis_mock):
        """Test TPH data endpoint with valid data"""
        redis_mock.get.return_value = json.dumps(SAMPLE_TPH_DATA)
        
        response = client.get("/api/v1/tph")
        
        assert response.status_code == 200
        assert response.json() == SAMPLE_TPH_DATA
        redis_mock.get.assert_called_once_with("tph")

    async def test_get_tph_data_not_found(self, client, redis_mock):
        """Test TPH data endpoint when no data is available"""
        redis_mock.get.return_value = None
        
        response = client.get("/api/v1/tph")
        
        assert response.status_code == 404
        assert response.json() == {"detail": "No TPH data available"}

    async def test_get_tph_data_invalid_json(self, client, redis_mock):
        """Test TPH data endpoint with invalid JSON data"""
        redis_mock.get.return_value = "invalid json"
        
        response = client.get("/api/v1/tph")
        
        assert response.status_code == 500
        assert response.json() == {"detail": "Error processing TPH data"}

    async def test_get_tph_data_invalid_timestamp(self, client, redis_mock):
        """Test TPH data endpoint with invalid timestamp format"""
        invalid_data = SAMPLE_TPH_DATA.copy()
        invalid_data["timestamp"] = "invalid-timestamp"
        redis_mock.get.return_value = json.dumps(invalid_data)
        
        response = client.get("/api/v1/tph")
        
        assert response.status_code == 500
        assert response.json() == {"detail": "Error processing TPH data"}

    async def test_get_tph_data_missing_fields(self, client, redis_mock):
        """Test TPH data endpoint with missing required fields"""
        invalid_data = {
            "temperature": 21.5,
            # missing pressure and humidity
            "timestamp": "2024-01-01T12:00:00"
        }
        redis_mock.get.return_value = json.dumps(invalid_data)
        
        response = client.get("/api/v1/tph")
        
        assert response.status_code == 500
        assert response.json() == {"detail": "Error processing TPH data"} 