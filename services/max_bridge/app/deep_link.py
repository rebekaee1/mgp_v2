"""Parser for ``?start=…`` deep-link payloads.

Background
==========

Partners like ``anytour.online`` (Pavel Pyatkoff) drive paid traffic from
Yandex.Direct + Telegram channels straight into their MAX bot via deep
links of the form::

    https://max.ru/<bot>?start=<payload>

Pavel uses a **structured convention** for the payload:

    utm_<source>_<key1>_<value1>_<key2>_<value2>…

Real-world examples he sent us:

    utm_ya_key_tury-v-turciyu_id_123456789
    utm_tg_to_rixos-turkey_from_kzn_id_12345
    utm_ya_key_poiskoviy_zapros_id_123456

Goal
====

The MAX webhook receives the raw payload string. We want two consumers
of that information:

1. **Lead tracking** — the verbatim payload must travel end-to-end so
   Pavel can correlate the lead with the originating ad in his analytics.
   This is why ``services/max_bridge/app/webhook.py`` still prefixes the
   user's first turn with ``[ИСТОЧНИК: <raw>]``.
2. **LLM context** — but the LLM should not have to guess that
   ``utm_ya_key_tury-v-turciyu_id_123456789`` means *"Яндекс.Директ,
   ключевая фраза 'туры в Турцию'"*. We decode it into a structured
   ``[КОНТЕКСТ: …]`` line that gets prepended alongside the raw marker.

The decoded line lets the assistant skip the *"куда хотите?"* round-trip
on hot, intent-rich traffic. Conversion uplift on similar deployments is
typically 15–25 % for queries with an explicit destination.

Design
======

* Source codes (`ya`, `tg`, `vk`, …) are looked up in a small static
  dictionary; unknown codes fall through to their literal value so we
  never lose information.
* Field keys (`key`, `to`, `from`, `id`, …) are also dictionary-driven.
  We split the payload by ``_`` and walk tokens, accumulating each
  value until the next *known* key (so hyphenated values like
  ``tury-v-turciyu`` survive intact).
* Payloads that don't match the ``utm_<source>_…`` prefix are returned
  with ``source=None`` and ``fields={}``. The caller will then label
  them as plain *"источник"* without a decoded context line.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, Optional


_SOURCE_LABELS: Dict[str, str] = {
    "ya": "Яндекс.Директ",
    "yandex": "Яндекс.Директ",
    "ydirect": "Яндекс.Директ",
    "tg": "Telegram-канал",
    "telegram": "Telegram-канал",
    "vk": "ВКонтакте",
    "ig": "Instagram",
    "instagram": "Instagram",
    "fb": "Facebook",
    "facebook": "Facebook",
    "gads": "Google Ads",
    "google": "Google Ads",
    "email": "Email-рассылка",
    "sms": "SMS-рассылка",
    "qr": "QR-код (офлайн)",
    "site": "Сайт партнёра",
    "organic": "Прямой переход",
}

_FIELD_LABELS: Dict[str, str] = {
    "key": "ключевая фраза",
    "kw": "ключевая фраза",
    "q": "поисковый запрос",
    "query": "поисковый запрос",
    "to": "оффер",
    "offer": "оффер",
    "hotel": "отель",
    "country": "страна",
    "city": "город",
    "from": "город вылета",
    "departure": "город вылета",
    "date": "дата",
    "nights": "количество ночей",
    "adults": "взрослых",
    "kids": "детей",
    "budget": "бюджет",
    "campaign": "кампания",
    "camp": "кампания",
    "id": "ID объявления",
    "ad": "ID объявления",
    "post": "ID поста",
    "channel": "канал",
}

# Render order — keeps the human label predictable regardless of the
# order the partner used inside the payload.
_FIELD_ORDER = (
    "country", "hotel", "offer", "to",
    "key", "kw", "q", "query",
    "from", "departure", "city",
    "date", "nights", "adults", "kids", "budget",
    "campaign", "camp", "channel",
    "id", "ad", "post",
)

_UTM_RE = re.compile(r"^utm_([A-Za-z0-9]+)(?:_(.+))?$", re.IGNORECASE)


@dataclass(frozen=True)
class ParsedPayload:
    """Result of :func:`parse_start_payload`.

    Attributes
    ----------
    raw : str
        The original payload string, trimmed but otherwise unchanged.
        Always present — used as the lead-tracking identifier.
    source : Optional[str]
        Lowercased source code (``ya``, ``tg``, …) when the payload
        follows the ``utm_<source>_…`` convention. ``None`` otherwise.
    fields : Dict[str, str]
        Decoded key/value map. Empty when ``source`` is ``None``.
    """

    raw: str
    source: Optional[str] = None
    fields: Dict[str, str] = field(default_factory=dict)

    @property
    def is_structured(self) -> bool:
        """True when we recognised the utm-style structure."""
        return self.source is not None


def parse_start_payload(payload: Optional[str]) -> ParsedPayload:
    """Parse a deep-link ``?start=`` code from MAX.

    Returns a :class:`ParsedPayload` — ``raw`` is always populated so
    callers can still log/track the original code even when the
    structure is unfamiliar.
    """
    if not payload:
        return ParsedPayload(raw="")
    raw = payload.strip()
    if not raw:
        return ParsedPayload(raw="")

    m = _UTM_RE.match(raw)
    if not m:
        return ParsedPayload(raw=raw)

    source = m.group(1).lower()
    tail = m.group(2) or ""
    if not tail:
        return ParsedPayload(raw=raw, source=source, fields={})

    tokens = tail.split("_")
    fields: Dict[str, str] = {}
    i = 0
    while i < len(tokens):
        key = tokens[i].lower()
        if key not in _FIELD_LABELS:
            # Unknown token — skip it. We accept some noise rather than
            # corrupt the parse: e.g. a stray ``ext`` segment shouldn't
            # eat the following ``id`` field.
            i += 1
            continue
        # Collect value tokens until the next *known* key.
        j = i + 1
        parts = []
        while j < len(tokens) and tokens[j].lower() not in _FIELD_LABELS:
            parts.append(tokens[j])
            j += 1
        if parts and key not in fields:
            # Hyphens are the value-internal word separator by
            # convention (slug-friendly). We preserve them here and
            # convert to spaces only at render time.
            fields[key] = "_".join(parts)
        i = j

    return ParsedPayload(raw=raw, source=source, fields=fields)


def _humanize_value(slug: str) -> str:
    """Convert a slug like ``tury-v-turciyu`` to ``tury v turciyu``.

    We deliberately do NOT transliterate (e.g. into Cyrillic): partner
    slugs frequently mix English hotel names (``rixos-turkey``) with
    transliterated Russian phrases (``tury-v-turciyu``), and a single
    static mapping can't handle both without corrupting one of them.
    Modern LLMs read transliterated Russian fluently, so we hand the
    slug over as-is and let the assistant interpret it in context.
    """
    return slug.replace("-", " ").strip()


def render_llm_context(parsed: ParsedPayload) -> str:
    """Compose the ``[КОНТЕКСТ: …]`` briefing line for the LLM.

    Returns an empty string when the payload didn't match the
    utm-convention — the caller should keep showing only the raw
    ``[ИСТОЧНИК: …]`` marker in that case.
    """
    if not parsed.is_structured:
        return ""

    src_label = _SOURCE_LABELS.get(parsed.source or "", parsed.source or "")
    bits = [f"канал: {src_label}"]
    for key in _FIELD_ORDER:
        if key not in parsed.fields:
            continue
        val = _humanize_value(parsed.fields[key])
        if not val:
            continue
        label = _FIELD_LABELS[key]
        bits.append(f"{label}: «{val}»")
    return "[КОНТЕКСТ: " + "; ".join(bits) + "]"


__all__ = [
    "ParsedPayload",
    "parse_start_payload",
    "render_llm_context",
]
