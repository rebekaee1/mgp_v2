"""Tour card renderers for MAX Messenger.

Produces the text + ``inline_keyboard`` attachment shapes expected by
``POST /messages``. Output is shaped to fit MAX Bot API constraints (markdown
quirks, 4000-char text cap, 2048-char URL cap, 7 buttons / row, button-type
restrictions documented in dev.max.ru/docs-api).

Conservatism rules of thumb baked into this module:

* User-supplied fields (hotel name, resort, operator, ...) are escaped before
  going into markdown so a stray ``*`` or ``[`` does not corrupt the layout
  for everything that follows.
* The single ``link`` button stays well under the 2048-char URL cap and we
  reject relative or non-http(s) URLs.
* Nothing here makes network calls — purely synchronous string building.
"""

from __future__ import annotations

import re
from typing import Any, Optional


_MD_ESCAPE_RE = re.compile(r"([*_~`\[\]\\<>])")

_MEAL_FALLBACK = {
    "RO": "Без питания",
    "BB": "Только завтрак",
    "HB": "Завтрак и ужин",
    "HB+": "Полупансион+",
    "FB": "Полный пансион",
    "FB+": "Полный пансион+",
    "AI": "Всё включено",
    "UAI": "Ультра всё включено",
}

_PAX_LABELS = {1: "за одного", 2: "за двоих", 3: "за троих", 4: "за четверых"}

_MAX_CAPTION_LEN = 3900  # safe envelope under MAX's 4000 hard cap
_MAX_LINK_URL_LEN = 2048


def _md_escape(text: Optional[str]) -> str:
    """Escape MAX markdown special characters so user text renders verbatim."""
    if not text:
        return ""
    return _MD_ESCAPE_RE.sub(r"\\\1", text)


def _format_stars(stars: Any) -> str:
    try:
        n = int(stars or 0)
    except (TypeError, ValueError):
        return ""
    return "⭐" * max(0, min(5, n))


def _format_rating(rating: Any) -> str:
    """Render rating as ``9.4`` (one decimal, trailing zero/dot stripped)."""
    try:
        r = float(rating or 0)
    except (TypeError, ValueError):
        return ""
    if r <= 0:
        return ""
    return f"{r:.1f}".rstrip("0").rstrip(".")


def _format_price(price: Any) -> str:
    """Format an integer price as ``410 000 ₽`` (NBSP thousands separator)."""
    try:
        n = int(price or 0)
    except (TypeError, ValueError):
        return ""
    if n <= 0:
        return ""
    return f"{n:,}".replace(",", " ") + " ₽"


def _format_date_short(d: Optional[str]) -> str:
    """``18.05.2026`` -> ``18.05``. Pass-through for unknown shapes."""
    if not d:
        return ""
    parts = d.split(".")
    if len(parts) >= 2:
        return f"{parts[0]}.{parts[1]}"
    return d


def _format_meal(card: dict[str, Any]) -> str:
    desc = (card.get("meal_description") or "").strip()
    if desc:
        return desc
    code = (card.get("food_type") or "").strip()
    if not code:
        return ""
    return _MEAL_FALLBACK.get(code, code)


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _format_pax(total: Any) -> str:
    """Label for the *total* number of travellers a price covers.

    ``total`` is adults + children (the price in a tour card is for the whole
    party). 1..4 use the natural Russian wording ("за двоих", "за троих"),
    5+ fall back to "за N человек".
    """
    n = _to_int(total)
    if n in _PAX_LABELS:
        return _PAX_LABELS[n]
    if n > 4:
        return f"за {n} человек"
    return ""


def _decline_children(n: int) -> str:
    """Russian plural for children: 1 ребёнок, 2-4 ребёнка, 5+ детей."""
    if n % 10 == 1 and n % 100 != 11:
        return "ребёнок"
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return "ребёнка"
    return "детей"


def _format_composition(adults: Any, children: Any) -> str:
    """Compact party composition, e.g. "2 взрослых + 1 ребёнок".

    Ages are intentionally omitted to keep the line short and always fit the
    card. Adults: "1 взрослый" / "N взрослых". Children appended only when > 0.
    """
    a = _to_int(adults)
    c = _to_int(children)
    parts: list[str] = []
    if a > 0:
        parts.append("1 взрослый" if a == 1 else f"{a} взрослых")
    if c > 0:
        parts.append(f"{c} {_decline_children(c)}")
    return " + ".join(parts)


def render_tour_card_caption(card: dict[str, Any]) -> str:
    """Markdown caption for one tour photo message.

    Example output::

        ⭐⭐⭐⭐⭐  *9.4*
        *Crystal Sunrise Queen Luxury*

        📍 Турция · Сиде
        📅 18.05 → 25.05 · 7 ночей
        🍽 Всё включено · 🛏 Standard Double
        ✈️ Перелёт включён · из Москвы
        👥 2 взрослых + 1 ребёнок

        *410 000 ₽* за троих
    """
    name = _md_escape(card.get("hotel_name") or "Отель")
    stars = _format_stars(card.get("hotel_stars"))
    rating = _format_rating(card.get("hotel_rating"))
    country = _md_escape(card.get("country"))
    resort = _md_escape(card.get("resort") or card.get("region"))
    date_from = _format_date_short(card.get("date_from"))
    date_to = _format_date_short(card.get("date_to"))
    try:
        nights = int(card.get("nights") or 0)
    except (TypeError, ValueError):
        nights = 0
    meal = _md_escape(_format_meal(card))
    room = _md_escape(card.get("room_type"))
    adults = card.get("adults")
    children = card.get("children")
    composition = _format_composition(adults, children)
    # Price in a tour card covers the whole party (adults + children). Hot
    # tours, however, are priced PER PERSON — keep that wording honest.
    if card.get("price_per_person"):
        pax_label = "за человека"
    else:
        pax_label = _format_pax(_to_int(adults) + _to_int(children))
    price_str = _format_price(card.get("price"))
    flight_included = bool(card.get("flight_included"))
    is_hotel_only = bool(card.get("is_hotel_only"))
    departure = _md_escape(card.get("departure_city"))

    header_parts: list[str] = []
    if stars:
        header_parts.append(stars)
    if rating:
        header_parts.append(f"**{rating}**")
    header = "  ".join(header_parts)

    location_parts: list[str] = []
    if country:
        location_parts.append(country)
    if resort and resort != country:
        location_parts.append(resort)
    location_line = "📍 " + " · ".join(location_parts) if location_parts else ""

    date_parts: list[str] = []
    if date_from and date_to:
        date_parts.append(f"{date_from} → {date_to}")
    elif date_from:
        date_parts.append(date_from)
    if nights > 0:
        date_parts.append(f"{nights} ночей")
    date_line = "📅 " + " · ".join(date_parts) if date_parts else ""

    extras: list[str] = []
    if meal:
        extras.append(f"🍽 {meal}")
    if room:
        extras.append(f"🛏 {room}")
    extras_line = " · ".join(extras)

    travel_parts: list[str] = []
    if is_hotel_only:
        travel_parts.append("🏨 Только отель")
    elif flight_included:
        if departure:
            travel_parts.append(f"✈️ Перелёт включён · из {departure}")
        else:
            travel_parts.append("✈️ Перелёт включён")
    # Operator name (Pegas, Coral, etc.) is intentionally NOT shown to the
    # end user — it's an internal supplier detail that adds visual noise
    # without buying decision value.
    travel_line = travel_parts[0] if travel_parts else ""

    price_line = ""
    if price_str:
        price_line = f"**{price_str}**"
        if pax_label:
            price_line += f" {pax_label}"

    lines: list[str] = []
    if header:
        lines.append(header)
    lines.append(f"**{name}**")
    lines.append("")
    if location_line:
        lines.append(location_line)
    if date_line:
        lines.append(date_line)
    if extras_line:
        lines.append(extras_line)
    if travel_line:
        lines.append(travel_line)
    if composition:
        lines.append(f"👥 {composition}")
    # Lead-catcher: короткая человеческая рекомендация (факты из данных +
    # правила курортов). Поле присутствует только для lead-catcher-тенантов;
    # для остальных карточек ключа нет → строка не добавляется (инертно).
    recommendation = _md_escape((card.get("recommendation") or "").strip())
    if recommendation:
        lines.append(f"💡 {recommendation}")
    if price_line:
        lines.append("")
        lines.append(price_line)

    text = "\n".join(lines).strip()
    if len(text) > _MAX_CAPTION_LEN:
        text = text[:_MAX_CAPTION_LEN].rstrip() + "…"
    return text


def render_tour_card_keyboard(card: dict[str, Any]) -> Optional[dict[str, Any]]:
    """Single-button [Забронировать] keyboard.

    Returns ``None`` when ``hotel_link`` is missing, relative, non-HTTP, or
    longer than MAX's 2048-char limit. The caller should still send the
    photo+caption in that case — just without the button.
    """
    link = (card.get("hotel_link") or "").strip()
    if not link:
        return None
    if not (link.startswith("https://") or link.startswith("http://")):
        return None
    if len(link) > _MAX_LINK_URL_LEN:
        return None
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {
                        "type": "link",
                        "text": "🔖 Забронировать",
                        "url": link,
                    }
                ]
            ]
        },
    }


def render_final_menu_text() -> str:
    return "Что дальше? 🌴"


# Payload sent (as a normal user message) when the client taps the subscription
# button. It is matched by system_prompt.md (subscription block) which then calls
# ``subscribe_tours`` — no callback handler needed, same mechanism as the menu.
SUBSCRIPTION_BUTTON_PAYLOAD = (
    "Хочу подписаться на мониторинг — пишите, когда появится подходящий "
    "или подешевеет тур"
)


def render_subscription_keyboard() -> dict[str, Any]:
    """Single ``message``-type button «🔔 Подписаться на мониторинг».

    Rendered (by the webhook) only when the backend sets ``offer_subscription``
    — i.e. at the hesitation moment for a pilot tenant with budget >= threshold.
    Tapping it sends ``SUBSCRIPTION_BUTTON_PAYLOAD`` through the normal chat
    pipeline, which triggers ``subscribe_tours``.
    """
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {
                        "type": "message",
                        "text": "🔔 Подписаться на мониторинг",
                        "payload": SUBSCRIPTION_BUTTON_PAYLOAD,
                    }
                ]
            ]
        },
    }


def render_welcome_after_reset() -> str:
    """One-shot reply sent after a user-triggered session reset.

    Deliberately short: no inline keyboard, no quick-start suggestions. The
    next message from the user will go through the normal pipeline with a
    fresh ``session_id`` and create a brand-new backend handler — the
    assistant's own greeting/slot-cascade takes over from there.
    """
    return "🆕 Готово, начинаем с чистого листа! Куда хотите поехать?"


def render_lead_catcher_menu_text() -> str:
    """Проактивная подводка под 2-й порцией карточек (lead-catcher)."""
    return (
        "Если пока ничего не зацепило — подберу дешевле, покажу ещё "
        "или передам менеджеру. Что удобнее? 👇"
    )


def render_quick_replies_keyboard(
    buttons: list[dict[str, Any]], per_row: int = 2
) -> Optional[dict[str, Any]]:
    """Клавиатура из произвольных ``message``-кнопок (lead-catcher, П.3).

    ``buttons`` — список ``{"text","payload"}``. Раскладываем по ``per_row`` в
    ряд. Возвращает None при пустом/некорректном списке (тогда вызывающий код
    откатывается на обычное меню).
    """
    rows: list[list[dict[str, Any]]] = []
    cur: list[dict[str, Any]] = []
    for b in buttons or []:
        text = (b.get("text") or "").strip()
        payload = (b.get("payload") or "").strip()
        if not text or not payload:
            continue
        cur.append({"type": "message", "text": text, "payload": payload})
        if len(cur) >= max(1, per_row):
            rows.append(cur)
            cur = []
    if cur:
        rows.append(cur)
    if not rows:
        return None
    return {"type": "inline_keyboard", "payload": {"buttons": rows}}


def render_final_menu_keyboard() -> dict[str, Any]:
    """Final menu under the cards (v2: card-anchored).

    All buttons are ``message`` type so the assistant handles them via the
    normal chat pipeline — no callback handler needed.

    Design notes:
    * Two refine actions (details + pagination) sit in row 1; the specific
      "Уточнить перелёт" lives in row 2 on its own to avoid label truncation
      in narrow MAX viewports (3-up rows clip text).
    * ``payload`` strings are intentionally short, natural Russian phrases.
      They map onto rules in ``system_prompt.md`` (see "MAX-меню после
      показа карточек" — same wording is matched there) so that nothing
      magic is needed in the bridge: the assistant simply receives a normal
      user message and replies according to the new rules. The "покажи
      ещё" payload reuses the long-standing phrase that the prompt already
      routes to ``continue_search``.
    """
    return {
        "type": "inline_keyboard",
        "payload": {
            "buttons": [
                [
                    {
                        "type": "message",
                        "text": "🔍 Уточнить детали",
                        "payload": "уточнить детали по варианту",
                    },
                    {
                        "type": "message",
                        "text": "📋 Показать ещё",
                        "payload": "покажи ещё",
                    },
                ],
                [
                    {
                        "type": "message",
                        "text": "✈️ Уточнить перелёт",
                        "payload": "уточнить перелёт по варианту",
                    },
                ],
            ]
        },
    }
