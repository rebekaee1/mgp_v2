"""Configuration for mgp-max-bridge.

All fields are populated from environment variables (prefix-less for compatibility
with the project-wide .env). Tenant routing is intentionally a method on the
Settings object instead of a hard-coded module-level dict so it can be reloaded
in tests and so additional tenants can be added with a single env var.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass(frozen=True)
class TenantBinding:
    """Maps an inbound MAX bot token to the matching mgp-backend tenant."""

    slug: str
    assistant_id: str
    bot_token: str


class Settings(BaseSettings):
    """Runtime settings, loaded from environment variables.

    Local development reads values from the project-root .env file (the same
    file the main backend uses). On production the values come from the
    docker-compose `env_file` directive plus per-service `environment:` keys.
    """

    model_config = SettingsConfigDict(
        env_file=None,  # docker-compose passes env via `env_file`/`environment`.
        env_prefix="",
        case_sensitive=False,
        extra="ignore",
    )

    max_bot_token_mgp_tour: str = Field(default="", description="Access token of the mgp-tour MAX bot")
    max_default_assistant_id: str = Field(
        default="593471b7-42da-4ae0-8499-904dcedd6a4b",
        description="Fallback assistant_id if a tenant cannot be resolved by token",
    )

    max_api_base_url: str = Field(default="https://botapi.max.ru")
    max_webhook_public_url: str = Field(default="")
    max_webhook_listen_port: int = Field(default=8090)

    max_backend_internal_url: str = Field(default="http://backend:8080")
    max_backend_service_token: str = Field(default="")

    max_redis_url: str = Field(default="redis://redis:6379/1")
    max_session_ttl_seconds: int = Field(default=86400)

    max_rate_limit_rps: int = Field(default=25)
    max_log_level: str = Field(default="INFO")

    backend_request_timeout_seconds: float = Field(default=60.0)
    max_api_request_timeout_seconds: float = Field(default=30.0)

    def tenant_bindings(self) -> list[TenantBinding]:
        """Return the list of currently configured tenant bots.

        Add new bots here when more branches are onboarded — adding a new env
        var (e.g. `MAX_BOT_TOKEN_MGP_VYHINO`) and wiring it to the right
        `assistant_id` is the only change required.
        """
        bindings: list[TenantBinding] = []
        if self.max_bot_token_mgp_tour:
            bindings.append(
                TenantBinding(
                    slug="mgp-tour",
                    assistant_id=self.max_default_assistant_id,
                    bot_token=self.max_bot_token_mgp_tour,
                )
            )
        return bindings

    def resolve_tenant_by_token(self, token: str) -> Optional[TenantBinding]:
        """Return the tenant binding that owns this MAX bot token, if any."""
        if not token:
            return None
        for tenant in self.tenant_bindings():
            if tenant.bot_token == token:
                return tenant
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor used by FastAPI dependencies and module-level code."""
    return Settings()
