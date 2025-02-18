"""
Data service that provides REST API endpoints to access sensor data from Redis cache.
"""

import json
import logging
from typing import Optional
from datetime import datetime

from pydantic import BaseModel
from redis.asyncio import Redis
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("data-service")


class HealthResponse(BaseModel):
    status: str

class TPHData(BaseModel):
    temperature: float
    pressure: float 
    humidity: float
    timestamp: str

class RedisClient:
    _instance: Optional[Redis] = None

    @classmethod
    async def get_instance(cls) -> Redis:
        if cls._instance is None:
            cls._instance = Redis(
                host="redis",
                port=6379,
                db=0,
                encoding="utf-8",
                decode_responses=True
            )
        return cls._instance

    @classmethod
    async def close(cls):
        if cls._instance is not None:
            await cls._instance.close()
            cls._instance = None


app = FastAPI(
    title="Sensor Data API",
    description="REST API for accessing sensor data",
    version="1.0.0"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


async def get_redis() -> Redis:
    """Dependency that provides Redis connection"""
    try:
        redis = await RedisClient.get_instance()
        await redis.ping()
        return redis
    except Exception as e:
        logger.error(f"Failed to connect to Redis: {e}")
        raise HTTPException(status_code=503, detail="Data store unavailable")

@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup Redis connection on shutdown"""
    await RedisClient.close()

@app.get("/health", response_model=HealthResponse)
async def health_check(redis: Redis = Depends(get_redis)):
    """Health check endpoint"""
    try:
        await redis.ping()
        return HealthResponse(status="healthy")
    except Exception:
        raise HTTPException(status_code=503, detail="Service unhealthy")

@app.get("/api/v1/tph", response_model=TPHData)
async def get_tph_data(redis: Redis = Depends(get_redis)):
    """
    Get the latest temperature, pressure, and humidity data.
    
    Returns:
        TPHData containing:
        - temperature (float): Temperature in Celsius
        - pressure (float): Pressure in hPa
        - humidity (float): Relative humidity percentage
        - timestamp (str): ISO format timestamp of the measurement
    """
    data = await redis.get("tph")
    
    if not data:
        raise HTTPException(status_code=404, detail="No TPH data available")
    
    try:
        tph_data = json.loads(data)
        # Convert timestamp string to ISO format
        timestamp = datetime.fromisoformat(tph_data['timestamp'])
        tph_data['timestamp'] = timestamp.isoformat()
        return TPHData(**tph_data)
    except Exception as e:
        logger.error(f"Error processing TPH data: {e}")
        raise HTTPException(status_code=500, detail="Error processing TPH data")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
