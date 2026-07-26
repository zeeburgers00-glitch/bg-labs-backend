import os
from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    DATABASE_URL: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/bg_labs"
    SECRET_KEY: str = "your-secret-key-change-in-production"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    DEBUG: bool = True

    # Redis (optional)
    REDIS_URL: str = "redis://localhost:6379"

    # TTS Settings
    TTS_MODEL: str = "xtts_v2"
    TTS_DEVICE: str = "auto"
    MAX_TEXT_LENGTH: int = 10000
    DEFAULT_LANGUAGE: str = "en"

    # Storage
    STORAGE_DIR: str = "storage"
    MAX_UPLOAD_SIZE: int = 50 * 1024 * 1024  # 50MB

    class Config:
        env_file = ".env"


@lru_cache
def get_settings():
    return Settings()
