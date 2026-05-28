"""Telegram-bot notifications for new leads & booking requests.

Used as an alternative / complement to e-mail and U-ON CRM. Wired so partners
who prefer to monitor leads in a Telegram chat (e.g. anytour.online — Pavel
Pyatkoff's pilot) receive a structured message per event.

How it works:
- ONE service bot for the whole system: token in env ``TELEGRAM_BOT_TOKEN``.
- Per-assistant target chat: ``widget_config.telegram_lead_chat_id`` (the
  Telegram numeric ID — positive for private DM with the user, negative
  starting with ``-100…`` for supergroups). For DMs the user must have
  already started the service bot at least once, otherwise Telegram
  rejects the message with HTTP 403 ``bot can't initiate conversation``.
- ``ENABLE_TELEGRAM_LEADS`` env flag — must be ``true`` to actually send.
  Off-by-default so partners with the field empty don't get any side
  effects.

The module exposes two callables — ``send_telegram_lead`` and
``send_telegram_booking`` — that mirror the e-mail senders but write to
Telegram instead. They never raise: a failed send is logged and returns
``{"ok": False, "error": "..."}`` so the LLM-side flow keeps going.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger("mgp_bot.telegram")

_TELEGRAM_API = "https://api.telegram.org"
_DEFAULT_TIMEOUT_S = 10.0


def _is_enabled() -> bool:
    """Soft kill-switch — ``ENABLE_TELEGRAM_LEADS=false`` disables every send."""
    return os.getenv("ENABLE_TELEGRAM_LEADS", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _service_bot_token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _escape_html(text: Any) -> str:
    """Telegram bot API parse_mode=HTML escaping (`< > &` only).

    See https://core.telegram.org/bots/api#html-style — Telegram is far less
    strict than e.g. browser HTML, but `&`, `<`, `>` must always be encoded.
    """
    s = "" if text is None else str(text)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _post(url: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    """Synchronous POST helper (the lead path runs in worker threads inside
    FastAPI; using a sync ``httpx.Client`` keeps it simple and avoids leaking
    event-loop concerns into the e-mail/CRM call-sites that already are sync).
    """
    try:
        with httpx.Client(timeout=_DEFAULT_TIMEOUT_S) as client:
            r = client.post(url, json=payload)
            try:
                body = r.json()
            except Exception:
                body = {"raw": r.text[:500]}
            if r.status_code == 200 and body.get("ok"):
                return {"ok": True, "result": body.get("result")}
            return {
                "ok": False,
                "error": f"HTTP {r.status_code}: {body.get('description') or body}",
            }
    except httpx.HTTPError as e:
        return {"ok": False, "error": f"transport: {e}"}
    except Exception as e:  # pragma: no cover — last-resort safety
        return {"ok": False, "error": f"unexpected: {e}"}


def _send_message(
    chat_id: str | int,
    text: str,
    *,
    parse_mode: str = "HTML",
    disable_web_page_preview: bool = False,
    bot_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Low-level sendMessage. Returns ``{ok, result|error}``."""
    if not _is_enabled():
        logger.info("📨 TG SEND skipped — ENABLE_TELEGRAM_LEADS=off")
        return {"ok": False, "error": "telegram leads disabled by env"}
    token = (bot_token or _service_bot_token()).strip()
    if not token:
        return {"ok": False, "error": "TELEGRAM_BOT_TOKEN is empty"}
    if not chat_id:
        return {"ok": False, "error": "chat_id is empty"}
    url = f"{_TELEGRAM_API}/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        "disable_web_page_preview": disable_web_page_preview,
    }
    return _post(url, payload)


def _format_money(value: Any) -> str:
    try:
        n = int(value)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return f"{n:,}".replace(",", " ") + " ₽"


def _extract_source_payload(client_request_summary: Optional[str]) -> Optional[str]:
    """Try to pull the original ``[ИСТОЧНИК: …]`` marker that max_bridge prefixed
    to the user's first turn. Bots that came via deep-link will have this in
    the conversation; widget users without payload will not.
    """
    if not client_request_summary:
        return None
    s = str(client_request_summary)
    marker = "[ИСТОЧНИК:"
    idx = s.find(marker)
    if idx < 0:
        return None
    end = s.find("]", idx)
    if end < 0:
        return None
    return s[idx + len(marker) : end].strip() or None


def send_telegram_lead(
    chat_id: str | int,
    *,
    client_name: str = "",
    client_phone: str = "",
    client_email: str = "",
    summary: str = "",
    source_payload: Optional[str] = None,
    agency_name: str = "",
    request_number: Optional[int] = None,
    tour_link: str = "",
    bot_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Lightweight lead notification — used for ``submit_client_request``
    (no specific tour, just contact + interest).

    ``tour_link`` (optional): if the lead targets a specific tour (LLM dropped
    a ``tourid=…`` reference in the comment), the caller can pass the
    pre-rendered booking URL here and we'll attach it as a clickable
    Telegram link, separately from the escaped ``summary`` body.
    """
    if not source_payload:
        source_payload = _extract_source_payload(summary)

    when = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = []
    title = "🆕 Новая заявка"
    if request_number:
        title = f"🆕 Заявка #{request_number}"
    lines.append(f"<b>{_escape_html(title)}</b>")
    if agency_name:
        lines.append(_escape_html(agency_name))
    lines.append("")
    if client_name:
        lines.append(f"👤 <b>{_escape_html(client_name)}</b>")
    if client_phone:
        lines.append(f"📞 <code>{_escape_html(client_phone)}</code>")
    if client_email:
        lines.append(f"✉️ {_escape_html(client_email)}")
    if summary:
        # Trim to avoid 4 096-char hard limit; conservative envelope of 3 000
        # leaves room for headers + footer.
        short = summary.strip()
        if len(short) > 3000:
            short = short[:3000] + "…"
        lines.append("")
        lines.append(_escape_html(short))
    if tour_link:
        lines.append("")
        lines.append(f"🔗 <a href=\"{_escape_html(tour_link)}\">Открыть карточку тура</a>")
    if source_payload:
        lines.append("")
        lines.append(f"📍 <b>Источник:</b> <code>{_escape_html(source_payload)}</code>")
    lines.append("")
    lines.append(f"<i>{_escape_html(when)}</i>")
    text = "\n".join(lines)

    res = _send_message(chat_id, text, bot_token=bot_token, disable_web_page_preview=True)
    if res.get("ok"):
        logger.info(
            "📨 TG LEAD sent chat=%s client=%s phone=%s payload=%s",
            chat_id, client_name[:32], client_phone[:32], source_payload or "",
        )
    else:
        logger.warning("📨 TG LEAD failed chat=%s err=%s", chat_id, res.get("error"))
    return res


def send_telegram_booking(
    chat_id: str | int,
    *,
    client_name: str = "",
    client_phone: str = "",
    client_email: str = "",
    hotel_name: str = "",
    country: str = "",
    resort: str = "",
    departure_city: str = "",
    fly_date: str = "",
    nights: int = 0,
    price: int = 0,
    operator: str = "",
    meal: str = "",
    room_type: str = "",
    stars: int = 0,
    tour_link: str = "",
    source_payload: Optional[str] = None,
    agency_name: str = "",
    request_number: Optional[int] = None,
    comment: str = "",
    bot_token: Optional[str] = None,
) -> Dict[str, Any]:
    """Booking notification — used when the LLM calls ``submit_booking_request``
    after the customer chose a specific tour.
    """
    when = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M")
    title = "✅ Запрос на бронирование"
    if request_number:
        title = f"✅ Бронь #{request_number}"

    star_str = "⭐" * max(0, min(int(stars or 0), 5))
    money = _format_money(price)

    lines: list[str] = []
    lines.append(f"<b>{_escape_html(title)}</b>")
    if agency_name:
        lines.append(_escape_html(agency_name))
    lines.append("")
    if client_name:
        lines.append(f"👤 <b>{_escape_html(client_name)}</b>")
    if client_phone:
        lines.append(f"📞 <code>{_escape_html(client_phone)}</code>")
    if client_email:
        lines.append(f"✉️ {_escape_html(client_email)}")
    lines.append("")
    if hotel_name:
        if star_str:
            lines.append(f"🏨 <b>{_escape_html(hotel_name)}</b> {star_str}")
        else:
            lines.append(f"🏨 <b>{_escape_html(hotel_name)}</b>")
    geo = ", ".join(p for p in [country, resort] if p)
    if geo:
        lines.append(f"🌍 {_escape_html(geo)}")
    if departure_city:
        lines.append(f"✈️ из {_escape_html(departure_city)}")
    if fly_date or nights:
        bits = []
        if fly_date:
            bits.append(_escape_html(fly_date))
        if nights:
            bits.append(f"{int(nights)} ночей")
        lines.append("📅 " + " · ".join(bits))
    if meal:
        lines.append(f"🍽 {_escape_html(meal)}")
    if room_type:
        lines.append(f"🛏 {_escape_html(room_type)}")
    if operator:
        lines.append(f"🛫 {_escape_html(operator)}")
    if money:
        lines.append(f"💰 <b>{_escape_html(money)}</b>")
    if tour_link:
        lines.append("")
        lines.append(f"🔗 <a href=\"{_escape_html(tour_link)}\">Открыть тур</a>")
    if comment:
        lines.append("")
        lines.append(f"📝 {_escape_html(comment)}")
    if source_payload:
        lines.append("")
        lines.append(f"🔗 <b>Источник:</b> <code>{_escape_html(source_payload)}</code>")
    lines.append("")
    lines.append(f"<i>{_escape_html(when)}</i>")
    text = "\n".join(lines)

    res = _send_message(chat_id, text, bot_token=bot_token)
    if res.get("ok"):
        logger.info(
            "📨 TG BOOKING sent chat=%s client=%s hotel=%s payload=%s",
            chat_id, client_name[:32], hotel_name[:48], source_payload or "",
        )
    else:
        logger.warning("📨 TG BOOKING failed chat=%s err=%s", chat_id, res.get("error"))
    return res


__all__ = [
    "send_telegram_lead",
    "send_telegram_booking",
    "_extract_source_payload",
    "_format_money",
    "_escape_html",
]
