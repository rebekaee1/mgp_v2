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

Tour cards (phase 2 v1)
-----------------------

After the assistant reply has been delivered, if ``chat_response.tour_cards``
is non-empty and ``settings.max_render_tour_cards`` is on, we render the
first N (default 3) tours as MAX photo-messages with a single
``Забронировать`` link button and append a final-menu message under them.
"""

from __future__ import annotations

import asyncio
import hmac
import re
from typing import Any, Optional

import httpx
import structlog
from fastapi import APIRouter, Header, HTTPException, Request, status

from .config import Settings, TenantBinding
from .chat_proxy import ChatProxy, ChatResponse
from .image_cache import ImageCache
from .max_api import MaxApiClient, MaxApiError
from .observability import new_correlation_id
from .renderers import (
    render_final_menu_keyboard,
    render_final_menu_text,
    render_tour_card_caption,
    render_tour_card_keyboard,
    render_welcome_after_reset,
)
from .session_store import SessionStore
from .text_splitter import split_for_max

router = APIRouter()
logger = structlog.get_logger("max_bridge.webhook")

# Headers we never log even by name, to avoid accidentally tipping off
# what auth scheme is in use to a malicious caller.
_SENSITIVE_HEADERS = {"authorization", "x-max-bot-api-secret", "cookie"}

# Slash-commands and full-text phrases that wipe the session and start over.
# The match is intentionally STRICT (whole message after lower-casing /
# trimming / normalising ``ё→е``) so accidental wording in the middle of a
# real query (e.g. "забудь всё что я говорил и подбери Турцию") does NOT
# trigger a reset. See system_prompt.md §17.2 for the surrounding context.
_RESET_SLASH = frozenset({"/restart", "/new", "/start", "/reset"})
_RESET_PHRASE_RE = re.compile(
    r"^(?:"
    r"начать заново"
    r"|начнем заново"
    r"|начнем сначала"
    r"|новый диалог|новый чат"
    r"|сброс|сбросить диалог|сбрось диалог|сбрось чат"
    r"|обнули контекст|обнулить контекст|обнули диалог|обнулить диалог"
    r"|забудь все"
    r"|reset|restart"
    r")[.!\s]*$"
)


def _is_reset_command(text: str) -> bool:
    """Return True if the inbound message is a *reset whole session* request.

    Matches:
    * whole-message slash-commands ``/restart``, ``/new``, ``/start``,
      ``/reset`` (no arguments — ``/start foo`` is treated as a deep-link,
      not a reset).
    * a curated list of Russian phrases; ``ё`` is normalised to ``е`` and
      trailing ``. ! whitespace`` is trimmed so user variations like
      ``"Начать заново."`` or ``"Забудь всё!"`` still match.
    """
    if not text:
        return False
    stripped = text.strip()
    if not stripped:
        return False
    head = stripped.split(None, 1)[0].lower()
    if head in _RESET_SLASH:
        return len(stripped.split()) == 1
    normalised = stripped.lower().replace("ё", "е")
    return _RESET_PHRASE_RE.match(normalised) is not None


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
            image_cache=request.app.state.image_cache,
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
    image_cache: ImageCache,
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
        # ── Reset command short-circuit ───────────────────────────────────
        # User can type /restart, /new, /start, /reset or a Russian phrase
        # ("начать заново", "забудь всё", …). We wipe the Redis session
        # mapping so the very next user message gets a fresh session_id and
        # a brand-new backend handler — no need to call the chat proxy here.
        if _is_reset_command(text):
            await session_store.reset_session(user_id)
            log.info("session_reset_by_user", trigger=text[:50])
            try:
                async with MaxApiClient(
                    base_url=settings.max_api_base_url,
                    bot_token=tenant.bot_token,
                    timeout=settings.max_api_request_timeout_seconds,
                ) as reset_client:
                    await reset_client.send_text(
                        chat_id=chat_id,
                        user_id=user_id if chat_id is None else None,
                        text=render_welcome_after_reset(),
                    )
            except MaxApiError as exc:
                log.error(
                    "reset_welcome_send_failed",
                    status=exc.status_code,
                    code=exc.code,
                    message=exc.message,
                )
            return

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

        async with MaxApiClient(
            base_url=settings.max_api_base_url,
            bot_token=tenant.bot_token,
            timeout=settings.max_api_request_timeout_seconds,
        ) as max_client:
            await _send_reply_chunks(
                max_client=max_client,
                chat_id=chat_id,
                user_id=user_id,
                reply=chat_response.reply,
                log=log,
            )
            if chat_response.tour_cards and settings.max_render_tour_cards:
                await _send_tour_cards(
                    max_client=max_client,
                    image_cache=image_cache,
                    settings=settings,
                    chat_id=chat_id,
                    user_id=user_id,
                    cards=chat_response.tour_cards,
                    log=log,
                )
            elif chat_response.tour_cards:
                log.info(
                    "tour_cards_disabled_by_flag",
                    count=len(chat_response.tour_cards),
                )
    except Exception:
        log.exception("webhook_processing_failed")


async def _send_reply_chunks(
    *,
    max_client: MaxApiClient,
    chat_id: Optional[int],
    user_id: int,
    reply: str,
    log: structlog.stdlib.BoundLogger,
) -> None:
    chunks = split_for_max(reply)
    if not chunks:
        log.warning("empty_reply_from_backend")
        return
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
            return


async def _send_tour_cards(
    *,
    max_client: MaxApiClient,
    image_cache: ImageCache,
    settings: Settings,
    chat_id: Optional[int],
    user_id: int,
    cards: list[dict[str, Any]],
    log: structlog.stdlib.BoundLogger,
) -> None:
    """Render the first N tour cards in parallel, then a final menu.

    Each card gathers its own image token (from cache or by downloading +
    uploading), then sends a single MAX message with photo + caption +
    booking-link keyboard. A failure in any single card falls back to a
    text-only card so the user always sees the data.
    """
    limit = max(1, settings.max_tour_cards_limit)
    selected = cards[:limit]
    log.info("tour_cards_render_start", count=len(selected), limit=limit, total=len(cards))

    results = await asyncio.gather(
        *(
            _send_one_tour_card(
                max_client=max_client,
                image_cache=image_cache,
                settings=settings,
                chat_id=chat_id,
                user_id=user_id,
                card=card,
                log=log.bind(card_index=i, hotel=card.get("hotel_name") or "?"),
            )
            for i, card in enumerate(selected, start=1)
        ),
        return_exceptions=True,
    )
    successes = sum(1 for r in results if r is True)
    log.info("tour_cards_render_done", successes=successes, attempted=len(selected))

    # Always send the final menu — even if some cards failed to render — so
    # the user has a clear next-step affordance.
    try:
        await max_client.send_message(
            chat_id=chat_id,
            user_id=user_id if chat_id is None else None,
            text=render_final_menu_text(),
            attachments=[render_final_menu_keyboard()],
        )
    except MaxApiError as exc:
        log.error(
            "final_menu_send_failed",
            status=exc.status_code,
            code=exc.code,
            message=exc.message,
        )


async def _send_one_tour_card(
    *,
    max_client: MaxApiClient,
    image_cache: ImageCache,
    settings: Settings,
    chat_id: Optional[int],
    user_id: int,
    card: dict[str, Any],
    log: structlog.stdlib.BoundLogger,
) -> bool:
    """Send one tour as photo + caption + keyboard (or text-only on failure).

    Returns ``True`` if MAX accepted *some* form of the card (with or without
    photo), ``False`` if even the text-only fallback failed.
    """
    caption = render_tour_card_caption(card)
    keyboard = render_tour_card_keyboard(card)
    image_url = (card.get("image_url") or "").strip()

    media_token: Optional[str] = None
    if image_url:
        media_token = await _resolve_image_token(
            max_client=max_client,
            image_cache=image_cache,
            settings=settings,
            image_url=image_url,
            log=log,
        )

    attachments: list[dict[str, Any]] = []
    if media_token:
        attachments.append({"type": "image", "payload": {"token": media_token}})
    if keyboard:
        attachments.append(keyboard)

    try:
        await max_client.send_message(
            chat_id=chat_id,
            user_id=user_id if chat_id is None else None,
            text=caption,
            attachments=attachments or None,
        )
        log.info("tour_card_sent", with_photo=media_token is not None, with_button=keyboard is not None)
        return True
    except MaxApiError as exc:
        # If the photo path failed (e.g. attachment.not.ready after retries)
        # and we still have a token, try once more without the photo so the
        # user at least sees the card text + booking button.
        log.warning(
            "tour_card_send_failed",
            with_photo=media_token is not None,
            status=exc.status_code,
            code=exc.code,
            message=exc.message,
        )
        if media_token is None:
            return False
        try:
            await max_client.send_message(
                chat_id=chat_id,
                user_id=user_id if chat_id is None else None,
                text=caption,
                attachments=[keyboard] if keyboard else None,
            )
            log.info("tour_card_sent_text_fallback")
            return True
        except MaxApiError as exc2:
            log.error(
                "tour_card_text_fallback_failed",
                status=exc2.status_code,
                code=exc2.code,
                message=exc2.message,
            )
            return False


async def _resolve_image_token(
    *,
    max_client: MaxApiClient,
    image_cache: ImageCache,
    settings: Settings,
    image_url: str,
    log: structlog.stdlib.BoundLogger,
) -> Optional[str]:
    """Look up a MAX media token for ``image_url`` (cache-aside).

    On any failure (cache error, image fetch error, MAX upload error) returns
    ``None`` so the caller can fall back to a text-only card. Successful
    uploads are cached for ``settings.max_image_cache_ttl_seconds``.
    """
    cached = await image_cache.get(image_url)
    if cached:
        log.info("image_cache_hit")
        return cached

    try:
        async with httpx.AsyncClient(timeout=settings.max_image_download_timeout) as fetch:
            response = await fetch.get(image_url)
        if response.status_code >= 400:
            log.warning("image_fetch_status", status=response.status_code)
            return None
        image_bytes = response.content
    except (httpx.HTTPError, asyncio.TimeoutError) as exc:
        log.warning("image_fetch_failed", error=str(exc))
        return None

    if not image_bytes:
        log.warning("image_fetch_empty")
        return None

    try:
        token = await max_client.upload_image_bytes(image_bytes)
    except MaxApiError as exc:
        log.warning("image_upload_failed", status=exc.status_code, code=exc.code, message=exc.message)
        return None

    await image_cache.set(image_url, token)
    log.info("image_uploaded_and_cached")
    return token
