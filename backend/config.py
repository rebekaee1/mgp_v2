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

    # --- U-ON CRM ---
    uon_api_key: str = ""
    uon_source: str = "AI-Ассистент"
    uon_dry_run: bool = True

    # --- МоиДокументы-Туризм CRM (moidokumenti.ru) ---
    moidoc_account_url: str = ""
    moidoc_api_key: str = ""
    moidoc_source: str = "AI-Ассистент"
    moidoc_dry_run: bool = True

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
    runtime_mode: str = "backend-only"  # runtime-only production mode
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
    runtime_dialog_sender_enabled: bool = True
    runtime_dialog_sender_batch_size: int = 20
    runtime_dialog_sender_interval_seconds: int = 10
    runtime_dialog_sender_timeout_seconds: int = 15
    runtime_dialog_sender_max_attempts: int = 5
    runtime_dialog_sender_retry_backoff_seconds: int = 10
    runtime_dialog_sender_retry_backoff_max_seconds: int = 300
    runtime_dialog_sender_normal_lag_threshold_seconds: int = 60
    runtime_dialog_sender_oldest_pending_alert_seconds: int = 300
    runtime_dialog_sender_failed_backlog_alert_threshold: int = 1
    runtime_provisioning_api_token: str = ""
    runtime_provisioning_callback_timeout_seconds: int = 15
    runtime_provisioning_callback_max_attempts: int = 3
    runtime_provisioning_callback_backoff_seconds: int = 2

    # --- Manager handoff (вход менеджера в чат, MAX) ---
    # Глобальный рубильник + allow-list ассистентов (CSV). По умолчанию ВЫКЛ:
    # пока operator_handoff_enabled=false ИЛИ assistant_id не в allow-list ИЛИ
    # канал не в operator_handoff_channels — фича полностью инертна (ноль влияния
    # на остальные диалоги/тенанты). Включаем только на тест-ассистенте 593471b7.
    operator_handoff_enabled: bool = False
    operator_handoff_assistant_ids: str = ""          # CSV allow-list assistant_id (канал MAX)
    operator_handoff_channels: str = "max"            # CSV каналов (старт: только max)
    operator_handoff_resume_minutes: int = 30         # авто-возврат к ИИ после тишины менеджера (safety-net)
    # --- Widget-handoff (вход менеджера в чат на сайте) ---
    # Канал 'widget' гейтится отдельно от MAX:
    #   • operator_handoff_widget_all_tenants=true → фича для ВСЕХ виджет-ассистентов
    #     (финальная раскатка «на всех, у кого есть виджет»);
    #   • иначе — точечный allow-list для виджета (обкатка, напр. МГП основной офис).
    # Канал должен также присутствовать в operator_handoff_channels. По умолчанию
    # widget полностью ВЫКЛ (channels=max), поэтому фича инертна для всех виджетов.
    operator_handoff_widget_all_tenants: bool = False
    operator_handoff_widget_assistant_ids: str = ""   # CSV allow-list assistant_id (канал widget)
    # Канал MAX «на всех»: true → handoff для ВСЕХ MAX-ассистентов (новые тенанты
    # подхватываются автоматически); false → точечный operator_handoff_assistant_ids.
    operator_handoff_max_all_tenants: bool = False
    # Секрет back-channel LK→MGP (заголовок X-MGP-Service-Token на /api/runtime/
    # operator/*). На стороне ЛК тот же VALUE лежит как MGP_OPERATOR_TOKEN.
    operator_handoff_token: str = ""
    # База MAX Bot API для прямой отправки операторского сообщения клиенту
    # (бэкенд берёт bot_token из runtime_metadata.channels.max). Совпадает с
    # MAX_API_BASE_URL моста.
    max_api_base_url: str = "https://botapi.max.ru"

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
