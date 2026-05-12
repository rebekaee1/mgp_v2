"""Tenant directory: pull MAX-channel bindings from mgp-backend.

When a new client is onboarded we add a row to
``assistants.runtime_metadata.channels.max`` in the prod database and the
bridge picks it up automatically — no env var, no code change, no restart.

The directory keeps an in-memory snapshot of all currently-active bindings.
On every webhook we look up by the ``webhook_secret`` MAX echoes back. A
background asyncio task refreshes the snapshot every
``settings.max_tenant_refresh_interval_seconds`` (default 60s) so the bridge
notices new bindings within roughly a minute without restarts.

Graceful degradation:

* If the backend is unreachable on startup, the directory falls back to the
  env-var binding (``settings.tenant_bindings()``) so a fresh bridge still
  works the way it did before this feature. The first successful refresh
  replaces that fallback.
* If a refresh fails after startup, we keep the previous in-memory snapshot
  rather than wipe it — short-lived backend hiccups must not 401 real users.
"""

from __future__ import annotations

import asyncio
from typing import Iterable, Optional

import httpx
import structlog

from .config import Settings, TenantBinding


class TenantDirectory:
    """Async-friendly cache of active MAX-channel tenant bindings."""

    def __init__(
        self,
        backend_url: str,
        *,
        service_token: str = "",
        request_timeout: float = 5.0,
        refresh_interval_seconds: int = 60,
        fallback_bindings: Optional[Iterable[TenantBinding]] = None,
    ) -> None:
        self._backend_url = backend_url.rstrip("/")
        self._service_token = service_token
        self._timeout = request_timeout
        self._refresh_interval = max(5, int(refresh_interval_seconds))
        # Map ``webhook_secret -> TenantBinding`` for O(1) resolution in the
        # webhook hot-path. Initial state is the env fallback so an empty
        # database / unreachable backend does not 401 every webhook.
        self._by_secret: dict[str, TenantBinding] = {
            tenant.webhook_secret: tenant
            for tenant in (fallback_bindings or ())
            if tenant.webhook_secret
        }
        self._initial_bindings: list[TenantBinding] = list(self._by_secret.values())
        self._lock = asyncio.Lock()
        self._log = structlog.get_logger("max_bridge.tenant_directory")
        self._stop_event = asyncio.Event()
        self._refresh_task: Optional[asyncio.Task] = None
        self._last_refresh_ok: bool = False
        self._last_refresh_count: int = len(self._by_secret)

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        request_timeout: float = 5.0,
        refresh_interval_seconds: int = 60,
    ) -> "TenantDirectory":
        return cls(
            backend_url=settings.max_backend_internal_url,
            service_token=settings.max_backend_service_token,
            request_timeout=request_timeout,
            refresh_interval_seconds=refresh_interval_seconds,
            fallback_bindings=settings.tenant_bindings(),
        )

    @property
    def known_count(self) -> int:
        return len(self._by_secret)

    @property
    def last_refresh_ok(self) -> bool:
        return self._last_refresh_ok

    def resolve_by_secret(self, secret: Optional[str]) -> Optional[TenantBinding]:
        """O(1) lookup for the webhook hot-path."""
        if not secret:
            return None
        return self._by_secret.get(secret.strip())

    async def refresh(self) -> bool:
        """Fetch the current bindings from backend; keep old cache on failure.

        Returns ``True`` if the refresh succeeded (even with zero rows), and
        ``False`` if the backend was unreachable / returned an error. In the
        latter case the existing in-memory snapshot is preserved.
        """
        url = f"{self._backend_url}/api/runtime/channels/max/bindings"
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._service_token:
            headers["X-MGP-Service-Token"] = self._service_token
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url, headers=headers)
        except (httpx.HTTPError, OSError) as exc:
            self._log.warning("tenant_directory_refresh_transport_failed", error=str(exc))
            self._last_refresh_ok = False
            return False

        if response.status_code >= 400:
            self._log.warning(
                "tenant_directory_refresh_bad_status",
                status=response.status_code,
            )
            self._last_refresh_ok = False
            return False

        try:
            payload = response.json()
        except ValueError:
            self._log.warning("tenant_directory_refresh_invalid_json")
            self._last_refresh_ok = False
            return False

        if not isinstance(payload, dict):
            self._log.warning("tenant_directory_refresh_unexpected_shape")
            self._last_refresh_ok = False
            return False

        raw_bindings = payload.get("bindings")
        if not isinstance(raw_bindings, list):
            self._log.warning("tenant_directory_refresh_no_list")
            self._last_refresh_ok = False
            return False

        new_map: dict[str, TenantBinding] = {}
        for row in raw_bindings:
            if not isinstance(row, dict):
                continue
            slug = (row.get("slug") or "").strip()
            assistant_id = (row.get("assistant_id") or "").strip()
            bot_token = (row.get("bot_token") or "").strip()
            webhook_secret = (row.get("webhook_secret") or "").strip()
            if not slug or not assistant_id or not bot_token or not webhook_secret:
                continue
            new_map[webhook_secret] = TenantBinding(
                slug=slug,
                assistant_id=assistant_id,
                bot_token=bot_token,
                webhook_secret=webhook_secret,
            )

        # If the backend returned an empty list we still keep the env
        # fallback so an unrelated DB issue (no migration applied yet) does
        # not wipe out a working tenant — defence in depth.
        if not new_map and self._initial_bindings:
            for fb in self._initial_bindings:
                new_map.setdefault(fb.webhook_secret, fb)

        async with self._lock:
            self._by_secret = new_map
            self._last_refresh_count = len(new_map)
            self._last_refresh_ok = True

        self._log.info(
            "tenant_directory_refreshed",
            count=len(new_map),
            slugs=sorted(b.slug for b in new_map.values()),
        )
        return True

    async def start(self) -> None:
        """Start the background refresh loop. Idempotent."""
        if self._refresh_task is not None:
            return
        await self.refresh()
        self._refresh_task = asyncio.create_task(self._refresh_loop(), name="tenant_directory_refresh")

    async def stop(self) -> None:
        """Stop the background refresh loop. Idempotent."""
        self._stop_event.set()
        task = self._refresh_task
        self._refresh_task = None
        if task is None:
            return
        try:
            await asyncio.wait_for(task, timeout=2.0)
        except (asyncio.TimeoutError, asyncio.CancelledError):
            task.cancel()

    async def _refresh_loop(self) -> None:
        try:
            while not self._stop_event.is_set():
                try:
                    await asyncio.wait_for(self._stop_event.wait(), timeout=self._refresh_interval)
                except asyncio.TimeoutError:
                    pass
                else:
                    # event was set → stop
                    return
                await self.refresh()
        except asyncio.CancelledError:
            return
