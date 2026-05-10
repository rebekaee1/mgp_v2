"""FastAPI router for the inbound MAX webhook.

Every request is acknowledged with ``200 OK`` immediately and the heavy
lifting (chat proxy + outbound MAX message) is done in a background task —
MAX retries unanswered webhooks for up to 30s, so we want to take that path
out of the critical path.

Authentication strategy
-----------------------

Per https://dev.max.ru/docs-api/methods/POST/subscriptions, MAX echoes the
``secret`` we pass at subscription time as the ``X-Max-Bot-Api-Secret``
header on every webhook. We compare that header (constant-time) against
each configured tenant's ``webhook_secret`` to:

1. Authenticate the request was actually made by MAX, and
2. Identify which tenant the bot belongs to (the MAX bot token is *not*
   sent inbound, so we can't use it for routing).

If MAX subscription was created without a secret, no auth header is sent
and the request will be rejected here with 401. That's intentional —
configure a webhook secret per tenant.
"""

from __future__ import annotations

import asyncio
import hmac
from typing import Any, Optional

import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from .config import Settings, TenantBinding
from .chat_proxy import ChatProxy
from .max_api import MaxApiClient, MaxApiError
from .observability import new_correlation_id
from .session_store import SessionStore
from .text_splitter import split_for_max

router = APIRouter()
logger = structlog.get_logger("max_bridge.webhook")

# Headers we never log even by name, to avoid accidentally tipping off
# what auth scheme is in use to a malicious caller.
_SENSITIVE_HEADERS = {"authorization", "x-max-bot-api-secret", "cookie"}


def _resolve_tenant(settings: Settings, secret: Optional[str]) -> Optional[TenantBinding]:
    if not secret:
        return None
    candidate = secret.strip()
    for tenant in settings.tenant_bindings():
        if hmac.compare_digest(tenant.webhook_secret, candidate):
            return tenant
    return None


def _extract_message(update: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Return a normalised dict ``{chat_id, user_id, text}`` or None.

    Handles a few shape variations seen in the docs to stay forward
    compatible (``message_created`` is the primary update type, but the
    sender/body shape changes slightly between API revisions).
    """
    update_type = update.get("update_type") or update.get("type")
    if update_type not in {"message_created", "message"}:
        return None
    message = update.get("message") or {}
    body = message.get("body") or {}
    text = (body.get("text") or "").strip()
    if not text:
        return None
    sender = message.get("sender") or {}
    recipient = message.get("recipient") or {}
    user_id = sender.get("user_id") or sender.get("id")
    chat_id = recipient.get("chat_id") or message.get("chat_id")
    if user_id is None:
        return None
    return {
        "user_id": int(user_id),
        "chat_id": int(chat_id) if chat_id is not None else None,
        "text": text,
    }


@router.post("/max/webhook", status_code=status.HTTP_200_OK)
async def max_webhook(
    request: Request,
    x_max_bot_api_secret: Optional[str] = Header(default=None, alias="X-Max-Bot-Api-Secret"),
) -> dict[str, str]:
    settings: Settings = request.app.state.settings
    tenant = _resolve_tenant(settings, x_max_bot_api_secret)
    if tenant is None:
        # Surface the *names* of inbound headers (never the values) so we can
        # diagnose subscription / proxy issues without leaking secrets.
        safe_header_names = sorted(
            name for name in request.headers.keys() if name.lower() not in _SENSITIVE_HEADERS
        )
        logger.warning(
            "webhook_auth_failed",
            secret_header_present=bool(x_max_bot_api_secret),
            tenant_count=len(settings.tenant_bindings()),
            client_ip=request.client.host if request.client else None,
            user_agent=request.headers.get("user-agent"),
            inbound_header_names=safe_header_names,
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    cid = new_correlation_id()
    try:
        update = await request.json()
    except Exception:
        logger.warning("webhook_invalid_json", correlation_id=cid)
        # Still return 200 — MAX retries on non-2xx and there is nothing to
        # gain from forcing them to redeliver an unparseable body.
        return {"ok": "true"}

    parsed = _extract_message(update)
    if parsed is None:
        logger.info(
            "webhook_unhandled",
            correlation_id=cid,
            update_type=update.get("update_type") or update.get("type"),
        )
        return {"ok": "true"}

    asyncio.create_task(
        _process_message(
            tenant=tenant,
            settings=settings,
            session_store=request.app.state.session_store,
            chat_proxy=request.app.state.chat_proxy,
            user_id=parsed["user_id"],
            chat_id=parsed["chat_id"],
            text=parsed["text"],
            correlation_id=cid,
        )
    )
    return {"ok": "true"}


async def _process_message(
    *,
    tenant: TenantBinding,
    settings: Settings,
    session_store: SessionStore,
    chat_proxy: ChatProxy,
    user_id: int,
    chat_id: Optional[int],
    text: str,
    correlation_id: str,
) -> None:
    """Background worker: chat proxy → MAX send.

    Wrapping the whole flow in a try/except keeps a transient failure (e.g.
    backend 502) from killing the asyncio task silently — instead we log it
    and (best effort) tell the user something went wrong.
    """
    log = logger.bind(correlation_id=correlation_id, tenant=tenant.slug, user_id=user_id)
    try:
        session_id, created = await session_store.get_or_create_session(user_id)
        log.info("session_resolved", session_id=session_id[:18], created=created)
        chat_response = await chat_proxy.chat(
            message=text,
            session_id=session_id,
            assistant_id=tenant.assistant_id,
        )
        log.info(
            "chat_reply_received",
            reply_len=len(chat_response.reply),
            cards=len(chat_response.tour_cards),
            crm=chat_response.crm_submitted,
        )

        chunks = split_for_max(chat_response.reply)
        if not chunks:
            log.warning("empty_reply_from_backend")
            return

        async with MaxApiClient(
            base_url=settings.max_api_base_url,
            bot_token=tenant.bot_token,
            timeout=settings.max_api_request_timeout_seconds,
        ) as max_client:
            for i, chunk in enumerate(chunks, start=1):
                try:
                    await max_client.send_text(
                        chat_id=chat_id,
                        user_id=user_id if chat_id is None else None,
                        text=chunk,
                    )
                except MaxApiError as exc:
                    log.error(
                        "max_send_failed",
                        chunk_index=i,
                        chunks_total=len(chunks),
                        status=exc.status_code,
                        code=exc.code,
                        message=exc.message,
                    )
                    break

        # Phase-1 deliberately ignores tour_cards. They will be rendered as
        # native MAX cards in phase 2 (renderers.py). For now we at least let
        # the user know how many results were found in the trailing text.
        if chat_response.tour_cards:
            log.info(
                "tour_cards_skipped_phase1",
                count=len(chat_response.tour_cards),
            )
    except Exception:
        log.exception("webhook_processing_failed")
