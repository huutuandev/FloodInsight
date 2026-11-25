from pydantic import AnyHttpUrl, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLOODINSIGHT_API_")

    environment: str = "development"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    read_timeout: float = Field(10, gt=0)
    processing_timeout: float = Field(180, gt=0)
    probe_timeout: float = Field(4, gt=0)
    ingestion_url: AnyHttpUrl = AnyHttpUrl("http://ingestion-service:8000")
    warehouse_url: AnyHttpUrl = AnyHttpUrl("http://warehouse-service:8000")
    analytics_url: AnyHttpUrl = AnyHttpUrl("http://analysis-service:8000")
    clustering_url: AnyHttpUrl = AnyHttpUrl("http://clustering-service:8000")
    prediction_url: AnyHttpUrl = AnyHttpUrl("http://prediction-service:8000")
    classification_url: AnyHttpUrl = AnyHttpUrl("http://classification-service:8000")

    @property
    def upstreams(self):
        return {
            name: str(getattr(self, name + "_url")).rstrip("/")
            for name in ("ingestion", "warehouse", "analytics", "clustering", "prediction", "classification")
        }
