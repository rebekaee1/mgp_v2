"""Redis-backed mapping from MAX user_id to mgp-backend session_id.

Sessions auto-expire 24h after the last write. The store is intentionally
async-only — both the webhook handler and the chat-proxy run inside the
asyncio event-loop, no sync codepath is needed.
"""

from __future__ import annotations

import uuid
from typing import Optional

from redis.asyncio import Redis


def _key(max_user_id: int | str, tenant_slug: Optional[str] = None) -> str:
    # The key is *scoped per tenant* on purpose: if the same MAX user writes
    # to two different MGP bots (e.g. mgp-tour and mgp-krasnogorsk), we must
    # NOT reuse the same backend session_id — the conversation row in the
    # mgp-backend DB is bound to a single ``assistant_id`` and is unique by
    # ``session_id``. Without the tenant scope the second bot's traffic
    # would silently land on the first bot's conversation (or fail with a
    # UNIQUE violation, as observed on 2026-05-13).
    #
    # When ``tenant_slug`` is omitted (legacy callers / tests that do not
    # care about isolation), we fall back to the original key shape so
    # behaviour is backwards-compatible.
    if tenant_slug:
        return f"max:user:{max_user_id}:tenant:{tenant_slug}:session"
    return f"max:user:{max_user_id}:session"


def _payload_key(max_user_id: int | str, tenant_slug: Optional[str] = None) -> str:
    """Separate Redis key for the deep-link ``payload`` we capture in
    ``bot_started`` and consume at the first user message.

    Lifecycle: SET on bot_started → GETDEL on first message → discarded.
    Scoped per tenant for the same reason as the session key.
    """
    if tenant_slug:
        return f"max:user:{max_user_id}:tenant:{tenant_slug}:start_payload"
    return f"max:user:{max_user_id}:start_payload"


class SessionStore:
    """Tiny abstraction over redis-py's async client.

    Owning the Redis connection makes it easy to swap a real client for
    fakeredis in unit tests.
    """

    def __init__(self, redis: Redis, ttl_seconds: int) -> None:
        self._redis = redis
        self._ttl = ttl_seconds

    @classmethod
    def from_url(cls, url: str, ttl_seconds: int) -> "SessionStore":
        # decode_responses=True makes the API return ``str`` instead of ``bytes``.
        return cls(Redis.from_url(url, decode_responses=True), ttl_seconds)

    async def aclose(self) -> None:
        await self._redis.aclose()

    async def get_session(
        self, max_user_id: int | str, tenant_slug: Optional[str] = None
    ) -> Optional[str]:
        return await self._redis.get(_key(max_user_id, tenant_slug))

    async def get_or_create_session(
        self, max_user_id: int | str, tenant_slug: Optional[str] = None
    ) -> tuple[str, bool]:
        """Return ``(session_id, created)``. Refreshes TTL on every hit."""
        key = _key(max_user_id, tenant_slug)
        existing = await self._redis.get(key)
        if existing:
            await self._redis.expire(key, self._ttl)
            return existing, False
        new_session = f"max-{max_user_id}-{uuid.uuid4().hex[:8]}"
        await self._redis.set(key, new_session, ex=self._ttl)
        return new_session, True

    async def reset_session(
        self, max_user_id: int | str, tenant_slug: Optional[str] = None
    ) -> None:
        await self._redis.delete(_key(max_user_id, tenant_slug))
        # If a user clicks the deep-link again after /restart, we want to
        # treat them as a fresh visit, so drop any stale pending payload too.
        await self._redis.delete(_payload_key(max_user_id, tenant_slug))

    async def set_pending_payload(
        self,
        max_user_id: int | str,
        payload: str,
        tenant_slug: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Stash a deep-link payload captured at ``bot_started``.

        Trimmed to MAX's documented 512-char limit; rejects empty strings.
        Uses a short TTL by default — payload is meant to flow into the very
        next user message, not to linger across days.
        """
        if not payload:
            return
        clean = payload.strip()[:512]
        if not clean:
            return
        ttl = ttl_seconds if ttl_seconds is not None else min(self._ttl, 3600)
        await self._redis.set(
            _payload_key(max_user_id, tenant_slug),
            clean,
            ex=ttl,
        )

    async def consume_pending_payload(
        self,
        max_user_id: int | str,
        tenant_slug: Optional[str] = None,
    ) -> Optional[str]:
        """Return and delete the pending payload (one-shot)."""
        key = _payload_key(max_user_id, tenant_slug)
        # Prefer GETDEL when the Redis server supports it (>=6.2).
        try:
            return await self._redis.getdel(key)
        except AttributeError:
            value = await self._redis.get(key)
            if value is not None:
                await self._redis.delete(key)
            return value

    async def ping(self) -> bool:
        return bool(await self._redis.ping())
