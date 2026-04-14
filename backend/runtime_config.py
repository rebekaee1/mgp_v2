from dataclasses import dataclass, field
import logging
import uuid
from typing import Any, Dict, Optional

from config import settings

logger = logging.getLogger("mgp_bot")


@dataclass
class RuntimeTenantConfig:
    assistant_id: Optional[str] = None
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    company_slug: Optional[str] = None
    company_logo_url: Optional[str] = None
    assistant_name: Optional[str] = None
    llm_provider: str = "openai"
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    openai_base_url: Optional[str] = None
    yandex_api_key: Optional[str] = None
    yandex_folder_id: Optional[str] = None
    yandex_model: Optional[str] = None
    tourvisor_login: Optional[str] = None
    tourvisor_pass: Optional[str] = None
    tourvisor_base_url: Optional[str] = None
    system_prompt: Optional[str] = None
    faq_content: Optional[str] = None
    allowed_domains: Optional[str] = None
    bot_server_url: Optional[str] = None
    widget_config: Dict[str, Any] = field(default_factory=dict)
    runtime_metadata: Dict[str, Any] = field(default_factory=dict)
    runtime_service_auth_secret: Optional[str] = None
    uon_api_key: Optional[str] = None
    uon_source: str = "AI-Ассистент"
    uon_dry_run: bool = True
    source: str = "env-default"


def build_default_runtime_config() -> RuntimeTenantConfig:
    return RuntimeTenantConfig(
        llm_provider=settings.llm_provider,
        llm_api_key=settings.openai_api_key or None,
        llm_model=settings.openai_model,
        openai_base_url=settings.openai_base_url,
        yandex_api_key=settings.yandex_api_key or None,
        yandex_folder_id=settings.yandex_folder_id or None,
        yandex_model=settings.yandex_model,
        tourvisor_login=settings.tourvisor_auth_login or None,
        tourvisor_pass=settings.tourvisor_auth_pass or None,
        tourvisor_base_url=settings.tourvisor_base_url,
        uon_api_key=settings.uon_api_key or None,
        uon_source=settings.uon_source,
        uon_dry_run=settings.uon_dry_run,
    )


def resolve_runtime_config(assistant_id: Optional[str] = None) -> RuntimeTenantConfig:
    runtime_config = build_default_runtime_config()
    if not assistant_id:
        return runtime_config

    try:
        assistant_uuid = uuid.UUID(str(assistant_id))
    except (ValueError, TypeError, AttributeError):
        logger.warning("Invalid assistant_id for runtime config: %s", assistant_id)
        return runtime_config

    try:
        from database import get_db, is_db_available
        from models import Assistant
    except Exception:
        logger.debug("Runtime config DB imports unavailable", exc_info=True)
        return runtime_config

    if not is_db_available():
        return runtime_config

    try:
        with get_db() as db:
            if db is None:
                return runtime_config

            assistant = db.query(Assistant).filter(
                Assistant.id == assistant_uuid,
                Assistant.is_active.is_(True),
            ).first()

            if not assistant:
                logger.warning("Assistant not found for runtime config: %s", assistant_id)
                return runtime_config

            runtime_config.assistant_id = str(assistant.id)
            runtime_config.company_id = str(assistant.company_id)
            runtime_config.company_name = getattr(assistant.company, "name", None)
            runtime_config.company_slug = getattr(assistant.company, "slug", None)
            runtime_config.company_logo_url = getattr(assistant.company, "logo_url", None)
            runtime_config.assistant_name = assistant.name
            runtime_config.llm_provider = (assistant.llm_provider or runtime_config.llm_provider or "openai").strip()
            runtime_config.llm_api_key = assistant.llm_api_key or runtime_config.llm_api_key
            runtime_config.llm_model = assistant.llm_model or runtime_config.llm_model
            runtime_config.tourvisor_login = assistant.tourvisor_login or runtime_config.tourvisor_login
            runtime_config.tourvisor_pass = assistant.tourvisor_pass or runtime_config.tourvisor_pass
            runtime_config.system_prompt = assistant.system_prompt or None
            runtime_config.faq_content = assistant.faq_content or None
            runtime_config.allowed_domains = assistant.allowed_domains or None
            runtime_config.bot_server_url = assistant.bot_server_url or None
            runtime_config.widget_config = dict(assistant.widget_config or {})
            runtime_config.runtime_metadata = dict(assistant.runtime_metadata or {})
            runtime_config.runtime_service_auth_secret = (
                (assistant.runtime_metadata or {}).get("service_auth", {}) or {}
            ).get("secret")
            runtime_config.uon_api_key = getattr(assistant, "uon_api_key", None) or runtime_config.uon_api_key
            runtime_config.uon_source = getattr(assistant, "uon_source", None) or runtime_config.uon_source
            runtime_config.source = "assistant-db"
            return runtime_config
    except Exception:
        logger.warning("Runtime config resolution failed for assistant_id=%s", assistant_id, exc_info=True)
        return runtime_config
