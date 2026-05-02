from functools import lru_cache
from os import getenv

from pydantic import BaseModel, Field


class Settings(BaseModel):
    app_name: str = "311 Live API"
    environment: str = Field(default_factory=lambda: getenv("ENVIRONMENT", "development"))
    log_level: str = Field(default_factory=lambda: getenv("LOG_LEVEL", "info"))
    backend_host: str = Field(default_factory=lambda: getenv("BACKEND_HOST", "127.0.0.1"))
    backend_port: int = Field(default_factory=lambda: int(getenv("BACKEND_PORT", "8000")))


@lru_cache
def get_settings() -> Settings:
    return Settings()
