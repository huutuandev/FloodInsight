from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOODINSIGHT_PREDICTION_")

    environment: str = "development"
    artifact_dir: str = "/models"
    flood_risk_config: str | None = None
