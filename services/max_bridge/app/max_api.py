"""Thin async client for the MAX Bot API (botapi.max.ru).

Only the endpoints we actually use are wrapped here. The auth header format
is ``Authorization: <bot_token>`` — note that the standard ``Bearer`` prefix
is **rejected** by botapi.max.ru (verified empirically on 2026-05-08).

The client deliberately exposes the raw response body for callers that need
diagnostic data (e.g. an unexpected MAX-side validation error) and lets
errors propagate so the caller can decide whether to retry.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, Optional

import httpx


class MaxApiError(RuntimeError):
    """Raised when the MAX Bot API returns a non-2xx response."""

    def __init__(self, status_code: int, code: str, message: str, raw: Any) -> None:
        super().__init__(f"MAX API {status_code} {code}: {message}")
        self.status_code = status_code
        self.code = code
        self.message = message
        self.raw = raw


@dataclass(frozen=True)
class BotIdentity:
    user_id: int
    username: Optional[str]
    name: str


class MaxApiClient:
    """Minimal async wrapper around https://botapi.max.ru.

    The class is async-context-friendly: ``async with MaxApiClient(...) as c``
    closes the underlying httpx client automatically.
    """

    def __init__(
        self,
        base_url: str,
        bot_token: str,
        *,
        timeout: float = 30.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._bot_token = bot_token
        # MAX rejects the standard "Bearer " prefix on /me, so we send the
        # raw token. Callers that hit other endpoints inherit the same header.
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout,
            headers={"Authorization": bot_token},
        )

    async def __aenter__(self) -> "MaxApiClient":
        return self

    async def __aexit__(self, *_exc) -> None:
        await self.aclose()

    async def aclose(self) -> None:
        await self._client.aclose()

    async def get_me(self) -> BotIdentity:
        data = await self._request("GET", "/me")
        return BotIdentity(
            user_id=int(data["user_id"]),
            username=data.get("username"),
            name=data.get("name") or data.get("first_name") or "",
        )

    async def send_text(
        self,
        *,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        text: str,
        markdown: bool = True,
        disable_link_preview: bool = False,
    ) -> dict[str, Any]:
        """Send a plain text message. Either chat_id or user_id is required.

        For 1-on-1 conversations the inbound webhook usually exposes a
        ``chat_id`` — that is the value to thread back here. ``user_id`` is a
        fallback when only the sender id is known.
        """
        if chat_id is None and user_id is None:
            raise ValueError("send_text requires chat_id or user_id")
        params: dict[str, Any] = {}
        if chat_id is not None:
            params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = user_id
        body: dict[str, Any] = {"text": text}
        if markdown:
            body["format"] = "markdown"
        if disable_link_preview:
            body["notify"] = True
            body["link_preview"] = False
        return await self._request("POST", "/messages", params=params, json=body)

    async def subscribe(self, webhook_url: str, *, secret: Optional[str] = None) -> dict[str, Any]:
        """Register the public webhook URL with MAX for this bot."""
        body: dict[str, Any] = {"url": webhook_url}
        if secret:
            body["secret"] = secret
        return await self._request("POST", "/subscriptions", json=body)

    async def list_subscriptions(self) -> dict[str, Any]:
        return await self._request("GET", "/subscriptions")

    async def unsubscribe(self, webhook_url: str) -> dict[str, Any]:
        return await self._request("DELETE", "/subscriptions", params={"url": webhook_url})

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[Mapping[str, Any]] = None,
        json: Any = None,
    ) -> dict[str, Any]:
        response = await self._client.request(method, path, params=params, json=json)
        if response.status_code >= 400:
            payload: Any
            try:
                payload = response.json()
            except Exception:
                payload = response.text
            code = ""
            message = ""
            if isinstance(payload, dict):
                code = str(payload.get("code") or "")
                message = str(payload.get("message") or "")
            raise MaxApiError(response.status_code, code, message, payload)
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"raw": response.text}
