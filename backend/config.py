"""
Централизованная конфигурация через pydantic-settings.
Singleton: `from config import settings` -- готовый объект.
Совместимость: Optional[] синтаксис для Python 3.9+.
"""

from functools import lru_cache
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- LLM ---
    llm_provider: str = "yandex"
    yandex_api_key: str = ""
    yandex_folder_id: str = ""
    yandex_model: str = "yandexgpt"
    openai_api_key: str = ""
    openai_base_url: Optional[str] = None
    openai_model: str = "gpt-5-mini"

    # --- TourVisor ---
    tourvisor_auth_login: str = ""
    tourvisor_auth_pass: str = ""
    tourvisor_base_url: str = "https://tourvisor.ru/xml"

    # --- PostgreSQL ---
    database_url: str = "postgresql://mgp:mgp@localhost:5432/mgp"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Server ---
    log_level: str = "INFO"
    log_format: str = "text"  # "text" | "json"
    gunicorn_workers: int = 1
    gunicorn_threads: int = 4
    session_ttl_seconds: int = 1800

    # --- Rate Limiting ---
    rate_limit_per_ip: int = 30
    rate_limit_per_session: int = 10


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
