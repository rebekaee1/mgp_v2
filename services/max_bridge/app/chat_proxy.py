"""Async client for mgp-backend POST /api/v1/chat.

The contract is documented in MAX_AGENT_HANDOFF.md §2.2 and
RUNTIME_DEPLOY.md (phase-1 LK auth). We deliberately do not parse the full
response shape into a typed object: the bridge passes ``reply`` and
``tour_cards`` straight to the renderer, and forwarding extra fields to
diagnostics is useful when something goes wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import quote

import httpx


def _ascii_safe_header(value: str) -> str:
    """RFC 7230 forbids non-ASCII bytes in HTTP header values. We percent-encode
    UTF-8 so a Cyrillic display name like ``"Наталия"`` can travel through
    the headers safely; the backend mirrors this with ``urllib.parse.unquote``.
    Without this httpx raises ``UnicodeEncodeError('ascii' codec…)`` on the
    POST and the whole MAX message silently drops on the floor.
    """
    return quote(value, safe="")


@dataclass
class ChatResponse:
    reply: str
    tour_cards: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: Optional[str] = None
    crm_submitted: bool = False
    offer_subscription: bool = False
    # Manager-handoff: backend выставляет suppressed=True, когда диалог в
    # operator_mode (менеджер за рулём) — ИИ не отвечает, мост НЕ шлёт клиенту
    # ничего (ни текст, ни карточки). Старый backend поле не присылает → False.
    suppressed: bool = False
    raw: dict[str, Any] = field(default_factory=dict)


class ChatProxy:
    """Talks to mgp-backend /api/v1/chat over an internal docker network."""

    def __init__(
        self,
        base_url: str,
        *,
        service_token: str = "",
        timeout: float = 60.0,
        client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._service_token = service_token
        self._client = client or httpx.AsyncClient(timeout=timeout)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def chat(
        self,
        *,
        message: str,
        session_id: str,
        assistant_id: str,
        external_user_id: Optional[str] = None,
        external_first_name: Optional[str] = None,
        external_last_name: Optional[str] = None,
        external_user_name: Optional[str] = None,
        external_chat_id: Optional[str] = None,
    ) -> ChatResponse:
        url = f"{self._base_url}/api/v1/chat"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Assistant-Id": assistant_id,
            # mgp-backend tags every conversation with the source channel on
            # the FIRST insert; the website widget never sets this header so
            # backend defaults to 'widget'. Keep this enum value in sync with
            # the LK side ``conversations.channel`` allowed list.
            "X-Channel": "max",
        }
        if external_user_id:
            # MAX user_id forwarded as a string so the backend can store it
            # without making assumptions about numeric range. Optional —
            # internal/test paths may omit a real user id.
            headers["X-External-User-Id"] = str(external_user_id)
        # The next four headers carry the channel-side user profile so the
        # backend can persist it on the conversation row and the LK can
        # render a "client card" without an extra round-trip to MAX. All
        # optional — only present if the bridge extracted them from the
        # MAX webhook payload. ``X-External-Chat-Id`` is the bot↔user
        # chat id; storing it gives the LK side a key to later send a
        # manager reply back into MAX via this bot, but we do not call
        # ``POST /messages`` here.
        if external_first_name:
            headers["X-External-User-First-Name"] = _ascii_safe_header(external_first_name)
        if external_last_name:
            headers["X-External-User-Last-Name"] = _ascii_safe_header(external_last_name)
        if external_user_name:
            headers["X-External-User-Name"] = _ascii_safe_header(external_user_name)
        if external_chat_id:
            # chat_id is always numeric in MAX so encoding is a no-op, but we
            # apply the same path for symmetry and future-proofing.
            headers["X-External-Chat-Id"] = _ascii_safe_header(str(external_chat_id))
        if self._service_token:
            headers["X-MGP-Service-Token"] = self._service_token
        body: dict[str, Any] = {
            "message": message,
            # mgp-backend treats conversation_id as the session key.
            "conversation_id": session_id,
            "assistant_id": assistant_id,
        }

        response = await self._client.post(url, headers=headers, json=body)
        # Even on 5xx the backend tries to return a JSON envelope ({reply,
        # tour_cards}) — we surface that to the user instead of silently
        # raising, so a degraded answer is still better than nothing.
        try:
            payload = response.json() if response.content else {}
        except ValueError:
            payload = {"reply": "", "tour_cards": []}
        if not isinstance(payload, dict):
            payload = {"reply": str(payload), "tour_cards": []}

        if response.status_code >= 500:
            response.raise_for_status()

        return ChatResponse(
            reply=str(payload.get("reply") or ""),
            tour_cards=list(payload.get("tour_cards") or []),
            conversation_id=payload.get("conversation_id"),
            crm_submitted=bool(payload.get("crm_submitted")),
            offer_subscription=bool(payload.get("offer_subscription")),
            suppressed=bool(payload.get("suppressed")),
            raw=payload,
        )
