from functools import lru_cache
from os import getenv

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "311 Live API"
    environment: str = Field(default_factory=lambda: getenv("ENVIRONMENT", "development"))
    log_level: str = Field(default_factory=lambda: getenv("LOG_LEVEL", "info"))
    backend_host: str = Field(default_factory=lambda: getenv("BACKEND_HOST", "127.0.0.1"))
    backend_port: int = Field(default_factory=lambda: int(getenv("BACKEND_PORT", "8000")))
    civic_context_mode: str = Field(
        default_factory=lambda: getenv("CIVIC_CONTEXT_MODE", "fallback")
    )
    socrata_app_token: str | None = Field(
        default_factory=lambda: getenv("SOCRATA_APP_TOKEN") or None
    )
    socrata_domain: str = Field(
        default_factory=lambda: getenv("SOCRATA_DOMAIN", "data.cityofnewyork.us")
    )
    socrata_service_requests_dataset: str = Field(
        default_factory=lambda: getenv("SOCRATA_SERVICE_REQUESTS_DATASET", "erm2-nwe9")
    )
    socrata_timeout_seconds: float = Field(
        default_factory=lambda: float(getenv("SOCRATA_TIMEOUT_SECONDS", "2.0"))
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
