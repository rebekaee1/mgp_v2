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
    ai_report_model: str = ""
    ai_report_api_key: str = ""

    # --- TourVisor ---
    tourvisor_auth_login: str = ""
    tourvisor_auth_pass: str = ""
    tourvisor_base_url: str = "https://tourvisor.ru/xml"

    # --- PostgreSQL ---
    database_url: str = "postgresql+psycopg://mgp:mgp@localhost:5432/mgp"

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Server ---
    log_level: str = "INFO"
    log_format: str = "text"  # "text" | "json"
    gunicorn_workers: int = 1
    gunicorn_threads: int = 4
    session_ttl_seconds: int = 1800

    # --- Widget ---
    widget_host_url: str = ""
    lk_widget_loader_url: str = "https://lk.navilet.ru/widget-loader.js"
    runtime_mode: str = "backend-only"  # legacy-web | backend-only
    backend_port: int = 8080

    # --- Runtime Security / Control Plane ---
    runtime_instance_id: str = ""
    runtime_public_base_url: str = ""
    runtime_service_auth_mode: str = "monitor"  # off | monitor | enforce
    runtime_service_auth_secret: str = ""
    runtime_service_auth_max_skew_seconds: int = 300
    runtime_trusted_proxy_cidrs: str = ""
    runtime_trusted_service_ids: str = "lk"
    runtime_allow_trusted_proxy_bypass: bool = True
    runtime_report_url: str = ""
    runtime_report_token: str = ""

    # --- Rate Limiting ---
    rate_limit_per_ip: int = 30
    rate_limit_per_session: int = 10

    # --- Dashboard Auth ---
    jwt_secret: str = "change-me-in-production-please"
    jwt_access_minutes: int = 30
    jwt_refresh_days: int = 7

    # --- Email (SMTP) ---
    smtp_host: str = "smtp.mail.ru"
    smtp_port: int = 465
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = ""
    smtp_use_ssl: bool = True


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
