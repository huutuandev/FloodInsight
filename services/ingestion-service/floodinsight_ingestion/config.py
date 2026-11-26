from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOODINSIGHT_INGESTION_")

    environment: str = "development"
    open_meteo_url: AnyHttpUrl = AnyHttpUrl("https://api.open-meteo.com/v1/forecast")
    scheduler_enabled: bool = True
    interval_seconds: int = Field(default=300, ge=1)
    timeout_seconds: float = Field(default=12, gt=0, le=60)
    max_attempts: int = Field(default=3, ge=1, le=5)
    # Include both the provider's current hour and the endpoint of the next
    # 24-hour decision window after the current receipt becomes eligible.
    past_hours: int = Field(default=72, ge=0, le=72)
    prediction_url: AnyHttpUrl | None = None
    warehouse_url: AnyHttpUrl | None = None
    soil_interval_seconds: int = Field(default=3600, ge=300)
    forecast_hours: int = Field(default=26, ge=1, le=48)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    db: str
    user: str
    password: SecretStr
