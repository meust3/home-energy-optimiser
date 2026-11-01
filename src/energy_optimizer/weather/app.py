"""App composition only; secrets stay in process memory, not the environment."""

from pathlib import Path

from energy_optimizer.home_assistant_app import AppHealth, HomeAssistantAppOptions
from energy_optimizer.persistence import open_bounded_weather_repository
from energy_optimizer.weather.collection import WeatherCollector
from energy_optimizer.weather.config import WeatherCollectionConfig
from energy_optimizer.weather.spool import WeatherSpool


def build_weather_collector(
    options: HomeAssistantAppOptions,
    *,
    database_url: str,
    health: AppHealth,
    spool_directory: Path = Path("/data/weather-spool"),
) -> WeatherCollector:
    config = WeatherCollectionConfig(
        enabled=options.weather_collection_enabled,
        provider_cap_confirmed=options.weather_provider_cap_confirmed,
        provider_daily_cap=options.weather_provider_daily_cap,
        api_key=options.weather_openweather_api_key.get_secret_value().strip(),
        latitude=options.weather_latitude,
        longitude=options.weather_longitude,
    )
    return WeatherCollector(
        config=config,
        spool=WeatherSpool(spool_directory),
        on_status=health.record_weather,
        repository_factory=lambda: open_bounded_weather_repository(database_url),
    )
