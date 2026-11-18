from pydantic import AnyHttpUrl, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOODINSIGHT_WAREHOUSE_")

    environment: str = "development"
    archive_url: AnyHttpUrl = AnyHttpUrl("https://archive-api.open-meteo.com/v1/archive")
    archive_timeout_seconds: float = Field(default=30, gt=0, le=120)
    archive_attempts: int = Field(default=3, ge=1, le=5)


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="POSTGRES_")

    host: str = "localhost"
    port: int = 5432
    db: str
    user: str
    password: SecretStr

    def url(self) -> URL:
        return URL.create(
            "postgresql+psycopg",
            username=self.user,
            password=self.password.get_secret_value(),
            host=self.host,
            port=self.port,
            database=self.db,
            query={"options": "-c timezone=UTC"},
        )
