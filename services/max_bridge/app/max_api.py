"""Thin async client for the MAX Bot API (botapi.max.ru).

Only the endpoints we actually use are wrapped here. The auth header format
is ``Authorization: <bot_token>`` — note that the standard ``Bearer`` prefix
is **rejected** by botapi.max.ru (verified empirically on 2026-05-08).

The client deliberately exposes the raw response body for callers that need
diagnostic data (e.g. an unexpected MAX-side validation error) and lets
errors propagate so the caller can decide whether to retry.
"""

from __future__ import annotations

import asyncio
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


# Per MAX docs: a freshly-uploaded media file may not be processed yet when
# the first /messages call arrives. We retry a couple of times with growing
# backoff before giving up so the surrounding caller can fall back gracefully.
_ATTACHMENT_NOT_READY_DELAYS = (0.0, 0.2, 0.5)
_ATTACHMENT_NOT_READY_CODE = "attachment.not.ready"


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
        self._timeout = timeout
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
        """Send a plain text message — thin wrapper over :meth:`send_message`.

        Kept for backward compatibility with callers that don't need
        attachments. Either chat_id or user_id is required.
        """
        return await self.send_message(
            chat_id=chat_id,
            user_id=user_id,
            text=text,
            attachments=None,
            fmt="markdown" if markdown else None,
            disable_link_preview=disable_link_preview,
        )

    async def send_message(
        self,
        *,
        chat_id: Optional[int] = None,
        user_id: Optional[int] = None,
        text: Optional[str] = None,
        attachments: Optional[list[dict[str, Any]]] = None,
        fmt: Optional[str] = "markdown",
        disable_link_preview: bool = False,
    ) -> dict[str, Any]:
        """Send a message with optional attachments.

        On a fresh ``attachment.not.ready`` from MAX (which happens when an
        image was uploaded a few hundred ms ago and is still being processed),
        retries up to two more times with a small backoff before giving up.
        """
        if chat_id is None and user_id is None:
            raise ValueError("send_message requires chat_id or user_id")
        params: dict[str, Any] = {}
        if chat_id is not None:
            params["chat_id"] = chat_id
        if user_id is not None:
            params["user_id"] = user_id
        body: dict[str, Any] = {}
        if text is not None:
            body["text"] = text
        if attachments:
            body["attachments"] = attachments
        if fmt:
            body["format"] = fmt
        if disable_link_preview:
            body["disable_link_preview"] = True

        last_error: Optional[MaxApiError] = None
        for delay in _ATTACHMENT_NOT_READY_DELAYS:
            if delay > 0:
                await asyncio.sleep(delay)
            try:
                return await self._request("POST", "/messages", params=params, json=body)
            except MaxApiError as exc:
                if exc.code != _ATTACHMENT_NOT_READY_CODE:
                    raise
                last_error = exc
        assert last_error is not None
        raise last_error

    async def upload_image_bytes(self, image_bytes: bytes) -> str:
        """Upload an image and return the MAX media token to attach to messages.

        Two-step flow per MAX docs:

        1. ``POST /uploads?type=image`` returns ``{url}`` — a one-shot signed
           CDN endpoint to receive the file body.
        2. ``POST <url>`` with multipart ``data=<file>`` returns ``{token}``
           which we then pass to ``/messages`` as
           ``attachments[].payload.token``.

        The upload step is performed with a fresh ``httpx.AsyncClient`` that
        deliberately omits our bot ``Authorization`` header — the CDN URL
        carries its own ``sig``/``expires`` query params and rejects extra
        auth.
        """
        if not image_bytes:
            raise ValueError("upload_image_bytes requires non-empty bytes")
        prep = await self._request("POST", "/uploads", params={"type": "image"})
        upload_url = prep.get("url")
        if not upload_url:
            raise MaxApiError(
                500,
                "upload.no_url",
                "MAX did not return an upload URL",
                prep,
            )
        async with httpx.AsyncClient(timeout=self._timeout) as cdn:
            response = await cdn.post(
                upload_url,
                files={"data": ("image.jpg", image_bytes, "image/jpeg")},
            )
        if response.status_code >= 400:
            try:
                payload: Any = response.json()
            except Exception:
                payload = response.text
            code = ""
            message = ""
            if isinstance(payload, dict):
                code = str(payload.get("code") or "")
                message = str(payload.get("message") or "")
            raise MaxApiError(response.status_code, code, message, payload)
        try:
            data = response.json()
        except ValueError as exc:
            raise MaxApiError(
                500,
                "upload.bad_response",
                "Upload CDN returned non-JSON response",
                response.text,
            ) from exc
        token = data.get("token") if isinstance(data, dict) else None
        if not token:
            raise MaxApiError(
                500,
                "upload.no_token",
                "Upload CDN response had no token",
                data,
            )
        return str(token)

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
