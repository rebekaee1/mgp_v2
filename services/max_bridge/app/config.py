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
    """Maps an inbound MAX bot to the matching mgp-backend tenant.

    Two secrets are kept per tenant:

    * ``bot_token`` — the access token issued by ``@MasterBot``. Used for
      *outbound* calls to ``botapi.max.ru`` (sending replies, managing
      subscriptions). Never sent by MAX to us.
    * ``webhook_secret`` — value we pass to ``POST /subscriptions`` as
      ``secret``. MAX echoes it back in the ``X-Max-Bot-Api-Secret`` header
      of every incoming webhook, which lets us authenticate the request
      and pick the matching tenant when several bots share one bridge.
    """

    slug: str
    assistant_id: str
    bot_token: str
    webhook_secret: str


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
    max_webhook_secret_mgp_tour: str = Field(
        default="",
        description=(
            "Per-tenant webhook secret. Passed to POST /subscriptions as `secret`; "
            "MAX echoes it back in X-Max-Bot-Api-Secret. Must match the regex "
            "^[A-Za-z0-9_-]{5,256}$ enforced by MAX."
        ),
    )
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

    # ── Phase 2 v1: tour_cards rendering ──────────────────────────────
    max_render_tour_cards: bool = Field(
        default=True,
        description=(
            "Master kill-switch for photo-card rendering. Set MAX_RENDER_TOUR_CARDS=0 "
            "in the env to instantly fall back to phase-1 behaviour (text-only)."
        ),
    )
    max_tour_cards_limit: int = Field(default=3, description="How many cards to render from chat_response.tour_cards")
    max_image_download_timeout: float = Field(default=5.0, description="seconds to wait when fetching the image from the source CDN")
    max_image_cache_ttl_seconds: int = Field(default=604800, description="how long to remember a hotel image → MAX media token (default 7 days)")

    def tenant_bindings(self) -> list[TenantBinding]:
        """Return the list of currently configured tenant bots.

        Add new bots here when more branches are onboarded — adding two new
        env vars (``MAX_BOT_TOKEN_MGP_VYHINO`` + ``MAX_WEBHOOK_SECRET_MGP_VYHINO``)
        and wiring them to the right ``assistant_id`` is the only change.

        A tenant entry is only emitted when *both* the bot token (for outbound
        calls) and the webhook secret (for inbound auth) are configured. A
        partially-configured tenant would silently 401 every webhook, so we
        skip it on purpose.
        """
        bindings: list[TenantBinding] = []
        if self.max_bot_token_mgp_tour and self.max_webhook_secret_mgp_tour:
            bindings.append(
                TenantBinding(
                    slug="mgp-tour",
                    assistant_id=self.max_default_assistant_id,
                    bot_token=self.max_bot_token_mgp_tour,
                    webhook_secret=self.max_webhook_secret_mgp_tour,
                )
            )
        return bindings

    def resolve_tenant_by_webhook_secret(self, secret: str) -> Optional[TenantBinding]:
        """Return the tenant binding whose webhook secret matches, if any."""
        if not secret:
            return None
        for tenant in self.tenant_bindings():
            if tenant.webhook_secret == secret:
                return tenant
        return None


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Cached accessor used by FastAPI dependencies and module-level code."""
    return Settings()
