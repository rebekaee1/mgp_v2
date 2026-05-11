"""Tenant-aware metadata fetcher for ``mgp-backend``.

Pulls per-tenant cosmetic settings (currently just the ``welcome_message``
that the client edits in dashboard → Widget Settings) and caches them in
Redis so the bridge does not re-hit the backend on every ``bot_started`` or
``/restart`` event.

Why this lives in the bridge (and not in renderers/text):

* The text is **owned by the client** in the dashboard. Hard-coding any
  welcome in the bridge image would make per-tenant content require a code
  deploy. That breaks the "as easy as widget" promise.
* The text is also per-tenant: scaling MAX to mgp-belgorod, mgp-vyhino, ...
  means we ask the backend ``GET /api/runtime/metadata?assistant_id=<id>``
  with their assistant_id and get *their* welcome. No bridge changes.
* If the backend is briefly unavailable or the field is empty, the caller
  gets ``None`` and falls back to a minimal hard-coded greeting — the bot
  is never silent on a fresh chat.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx
import structlog
from redis.asyncio import Redis


class RuntimeMetadataClient:
    """Async client for ``GET /api/runtime/metadata`` with Redis cache.

    The cache key is namespaced by ``assistant_id`` so multi-tenant
    deployments (Phase-3) share the same code path without changes.
    """

    KEY_PREFIX = "max:welcome:"
    _NULL_MARKER = "\x00"  # tiny sentinel to cache "no welcome set" misses

    def __init__(
        self,
        backend_url: str,
        redis_client,
        *,
        service_token: str = "",
        cache_ttl_seconds: int = 600,
        request_timeout: float = 5.0,
    ) -> None:
        self._backend_url = backend_url.rstrip("/")
        self._redis = redis_client
        self._service_token = service_token
        self._cache_ttl = cache_ttl_seconds
        self._timeout = request_timeout
        self._log = structlog.get_logger("max_bridge.runtime_meta")

    @classmethod
    def from_url(
        cls,
        backend_url: str,
        redis_url: str,
        *,
        service_token: str = "",
        cache_ttl_seconds: int = 600,
        request_timeout: float = 5.0,
    ) -> "RuntimeMetadataClient":
        return cls(
            backend_url=backend_url,
            redis_client=Redis.from_url(redis_url, decode_responses=True),
            service_token=service_token,
            cache_ttl_seconds=cache_ttl_seconds,
            request_timeout=request_timeout,
        )

    async def aclose(self) -> None:
        try:
            await self._redis.aclose()
        except AttributeError:
            # fakeredis FakeRedis exposes close() instead of aclose() in older
            # versions — best-effort cleanup, not a real failure mode.
            pass

    async def get_welcome_message(self, assistant_id: str) -> Optional[str]:
        """Return the per-tenant welcome message, or None.

        ``None`` means "no per-tenant welcome configured" — the caller must
        decide its own fallback (typically a minimal hard-coded greeting).
        Network / cache errors are swallowed and surfaced as ``None`` so
        bridge keeps running.
        """
        if not assistant_id:
            return None
        cache_key = self.KEY_PREFIX + assistant_id

        # ── 1. Try Redis cache ──────────────────────────────────────────
        try:
            cached = await self._redis.get(cache_key)
        except Exception:
            self._log.exception("welcome_cache_get_failed", assistant_id=assistant_id)
            cached = None
        if cached is not None:
            if cached == self._NULL_MARKER:
                return None
            return cached

        # ── 2. Fetch from backend /api/runtime/metadata ─────────────────
        welcome = await self._fetch_from_backend(assistant_id)

        # ── 3. Store result in cache (both hits and known-empty) ────────
        try:
            stored = welcome if welcome else self._NULL_MARKER
            await self._redis.set(cache_key, stored, ex=self._cache_ttl)
        except Exception:
            self._log.exception("welcome_cache_set_failed", assistant_id=assistant_id)

        return welcome

    async def _fetch_from_backend(self, assistant_id: str) -> Optional[str]:
        url = f"{self._backend_url}/api/runtime/metadata"
        headers: dict[str, str] = {"X-Assistant-Id": assistant_id}
        if self._service_token:
            # Even though /api/runtime/metadata is currently open to the
            # internal docker network, we still send the service token so
            # the endpoint can flip to a stricter auth mode later without
            # the bridge needing redeployment.
            headers["X-MGP-Service-Token"] = self._service_token
        params = {"assistant_id": assistant_id}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, params=params, headers=headers)
        except (httpx.HTTPError, OSError) as exc:
            self._log.warning(
                "welcome_fetch_failed",
                assistant_id=assistant_id,
                error=str(exc),
            )
            return None
        if response.status_code >= 400:
            self._log.warning(
                "welcome_fetch_status",
                assistant_id=assistant_id,
                status=response.status_code,
            )
            return None
        try:
            payload: Any = response.json()
        except ValueError:
            self._log.warning("welcome_fetch_invalid_json", assistant_id=assistant_id)
            return None
        if not isinstance(payload, dict):
            return None
        tenant = payload.get("tenant") or {}
        branding = tenant.get("branding") or {}
        welcome = branding.get("welcome_message")
        if isinstance(welcome, str):
            cleaned = welcome.strip()
            return cleaned or None
        return None

    async def invalidate(self, assistant_id: str) -> None:
        """Drop the cached welcome for one tenant — used by tests."""
        if not assistant_id:
            return
        try:
            await self._redis.delete(self.KEY_PREFIX + assistant_id)
        except Exception:
            self._log.exception("welcome_cache_invalidate_failed", assistant_id=assistant_id)
