"""FastAPI entrypoint for mgp-max-bridge.

Lifespan owns long-lived async resources (Redis pool, httpx clients) so
they share connection state across all requests.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

import structlog
from fastapi import FastAPI

from .chat_proxy import ChatProxy
from .config import Settings, get_settings
from .image_cache import ImageCache
from .observability import configure_logging
from .runtime_meta import RuntimeMetadataClient
from .session_store import SessionStore
from .webhook import router as webhook_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings: Settings = get_settings()
    configure_logging(settings.max_log_level)
    logger = structlog.get_logger("max_bridge.lifespan")

    session_store = SessionStore.from_url(
        settings.max_redis_url, ttl_seconds=settings.max_session_ttl_seconds
    )
    chat_proxy = ChatProxy(
        base_url=settings.max_backend_internal_url,
        service_token=settings.max_backend_service_token,
        timeout=settings.backend_request_timeout_seconds,
    )
    image_cache = ImageCache.from_url(
        settings.max_redis_url, ttl_seconds=settings.max_image_cache_ttl_seconds
    )
    runtime_meta = RuntimeMetadataClient.from_url(
        backend_url=settings.max_backend_internal_url,
        redis_url=settings.max_redis_url,
        service_token=settings.max_backend_service_token,
        cache_ttl_seconds=settings.max_welcome_cache_ttl_seconds,
        request_timeout=settings.max_metadata_request_timeout,
    )

    redis_ok = False
    try:
        redis_ok = await session_store.ping()
    except Exception:
        # Redis can be unreachable on cold-start; we still let the service
        # boot so /health reports the failure rather than crashing on launch.
        logger.warning("redis_ping_failed_on_startup", exc_info=True)

    app.state.settings = settings
    app.state.session_store = session_store
    app.state.chat_proxy = chat_proxy
    app.state.image_cache = image_cache
    app.state.runtime_meta = runtime_meta
    app.state.redis_ok_on_start = redis_ok

    tenant_count = len(settings.tenant_bindings())
    logger.info(
        "max_bridge_started",
        backend=settings.max_backend_internal_url,
        tenant_count=tenant_count,
        webhook=settings.max_webhook_public_url or "<not_set>",
        redis_ok=redis_ok,
        render_tour_cards=settings.max_render_tour_cards,
        tour_cards_limit=settings.max_tour_cards_limit,
        welcome_from_backend=settings.max_welcome_from_backend,
    )
    try:
        yield
    finally:
        await chat_proxy.aclose()
        await session_store.aclose()
        await image_cache.aclose()
        await runtime_meta.aclose()
        logger.info("max_bridge_stopped")


app = FastAPI(title="mgp-max-bridge", version="0.1.0", lifespan=lifespan)
app.include_router(webhook_router)


@app.get("/health")
async def health() -> dict[str, Any]:
    settings: Settings = app.state.settings
    redis_ok = False
    try:
        redis_ok = await app.state.session_store.ping()
    except Exception:
        redis_ok = False

    return {
        "status": "ok" if redis_ok else "degraded",
        "redis": "ok" if redis_ok else "down",
        "tenants": len(settings.tenant_bindings()),
        "backend_url": settings.max_backend_internal_url,
        "webhook_public_url": settings.max_webhook_public_url or None,
    }
