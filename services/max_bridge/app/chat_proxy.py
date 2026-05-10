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

import httpx


@dataclass
class ChatResponse:
    reply: str
    tour_cards: list[dict[str, Any]] = field(default_factory=list)
    conversation_id: Optional[str] = None
    crm_submitted: bool = False
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
    ) -> ChatResponse:
        url = f"{self._base_url}/api/v1/chat"
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "X-Assistant-Id": assistant_id,
        }
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
            raw=payload,
        )
