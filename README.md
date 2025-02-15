# Arkadia

Arkadia is a project to monitor home environment conditions like temperature, pressure, humidity, and air quality. The goal is to practice working with sensors and various software architecture patterns. All services and sensors are currently running on a single Raspberry Pi 5.

Arkadia is named after the base camp of the Skaikru people in [the TV show "The 100"](https://en.wikipedia.org/wiki/The_100_(TV_series)).

## Getting Started

```bash
cd services
docker compose up
```

## Services

### tph

This service measures temperature, prressure and humidity using a BME280 sensor and a Raspberry Pi. It periodically samples sensor data and stores the median values in a Redis cache.

```bash
docker compose run tph
```
