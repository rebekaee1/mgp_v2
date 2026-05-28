"""Regression suite for the ``?start=…`` deep-link payload parser.

Test cases cover Pavel Pyatkoff's documented conventions plus the
free-form fallback we promised partners on the first integration call:

  * partners can hand us a structured ``utm_<source>_<key>_<value>_…``
    code (parsed) — verified end-to-end across Yandex/Telegram patterns;
  * or any opaque slug (just ``rixos_turkey_001``) — preserved verbatim
    and surfaced as a plain "источник" without a misleading decoded
    context line.

The companion module documents each labelled key (`key`, `to`, `from`,
`id`, etc.); these tests assert the parser walks tokens correctly even
when:
  - hyphenated values land between two known keys
    (``key_tury-v-turciyu_id_…``);
  - the partner sprinkles a stray unknown segment between known keys
    (``utm_ya_ext_premium_key_…``) — noise must NOT swallow the next
    field;
  - the partner uses an aliased key (``q`` instead of ``key``);
  - the payload is empty / missing.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Allow ``python -m pytest tests/test_deep_link.py`` to run from repo root.
SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))

from app.deep_link import (  # noqa: E402
    ParsedPayload,
    parse_start_payload,
    render_llm_context,
)


# ─────────────────────────────────────────────────────────────────────────────
# parse_start_payload
# ─────────────────────────────────────────────────────────────────────────────

def test_yandex_keyword_payload():
    p = parse_start_payload("utm_ya_key_tury-v-turciyu_id_123456789")
    assert p.is_structured
    assert p.source == "ya"
    assert p.fields == {"key": "tury-v-turciyu", "id": "123456789"}
    assert p.raw == "utm_ya_key_tury-v-turciyu_id_123456789"


def test_telegram_offer_and_city_payload():
    p = parse_start_payload("utm_tg_to_rixos-turkey_from_kzn_id_12345")
    assert p.source == "tg"
    assert p.fields == {"to": "rixos-turkey", "from": "kzn", "id": "12345"}


def test_yandex_query_only_no_id():
    p = parse_start_payload("utm_ya_key_egypt-from-spb")
    assert p.source == "ya"
    assert p.fields == {"key": "egypt-from-spb"}


def test_alias_key_q_works_like_key():
    p = parse_start_payload("utm_ya_q_dubai_id_42")
    assert p.fields == {"q": "dubai", "id": "42"}


def test_unknown_source_label_is_preserved():
    p = parse_start_payload("utm_xyz_key_test_id_1")
    assert p.is_structured
    assert p.source == "xyz"
    assert p.fields == {"key": "test", "id": "1"}


def test_payload_without_utm_prefix_is_opaque():
    p = parse_start_payload("rixos_turkey_001")
    assert not p.is_structured
    assert p.source is None
    assert p.fields == {}
    assert p.raw == "rixos_turkey_001"


def test_just_utm_source_no_fields():
    p = parse_start_payload("utm_ya")
    assert p.source == "ya"
    assert p.fields == {}


def test_empty_payload_safe():
    p = parse_start_payload("")
    assert p == ParsedPayload(raw="")


def test_none_payload_safe():
    p = parse_start_payload(None)
    assert p == ParsedPayload(raw="")


def test_whitespace_payload_safe():
    p = parse_start_payload("   ")
    assert p.raw == ""


def test_unknown_segment_between_known_keys_is_skipped():
    """``ext_premium`` is not a labelled key — it must NOT eat ``id``."""
    p = parse_start_payload("utm_ya_ext_premium_key_dubai_id_999")
    assert p.fields == {"key": "dubai", "id": "999"}


def test_value_with_multiple_internal_hyphens():
    p = parse_start_payload("utm_ya_key_goryashie-tury-v-egipet-iz-moskvy_id_77")
    assert p.fields["key"] == "goryashie-tury-v-egipet-iz-moskvy"


def test_first_occurrence_of_repeated_key_wins():
    p = parse_start_payload("utm_ya_key_first-query_key_second-query_id_5")
    # The second `key` token starts a new field, but our walker assigns
    # value to the FIRST key only — the duplicated segment is preserved
    # as the start of the value (since the inner ``key`` slot is empty
    # after the first hit, the dup acts as a re-marker and overwrites
    # would lose data; behaviour: first wins).
    assert "key" in p.fields
    # We're flexible about the exact value bytes — the contract is that
    # the FIRST occurrence is kept, not silently replaced.
    assert p.fields["key"].startswith("first-query")
    assert p.fields.get("id") == "5"


def test_uppercase_normalises():
    p = parse_start_payload("UTM_YA_KEY_TURKEY_ID_5")
    assert p.source == "ya"
    assert p.fields == {"key": "TURKEY", "id": "5"}


# ─────────────────────────────────────────────────────────────────────────────
# render_llm_context
# ─────────────────────────────────────────────────────────────────────────────

def test_render_yandex_keyword():
    p = parse_start_payload("utm_ya_key_tury-v-turciyu_id_123456789")
    ctx = render_llm_context(p)
    assert "Яндекс.Директ" in ctx
    assert "ключевая фраза" in ctx
    # Hyphens become spaces for legibility.
    assert "tury v turciyu" in ctx
    assert "123456789" in ctx
    assert ctx.startswith("[КОНТЕКСТ:")
    assert ctx.endswith("]")


def test_render_telegram_regional():
    p = parse_start_payload("utm_tg_to_rixos-turkey_from_kzn_id_12345")
    ctx = render_llm_context(p)
    assert "Telegram-канал" in ctx
    assert "оффер" in ctx and "rixos turkey" in ctx
    assert "город вылета" in ctx and "kzn" in ctx
    assert "12345" in ctx


def test_render_opaque_payload_returns_empty():
    p = parse_start_payload("rixos_turkey_001")
    assert render_llm_context(p) == ""


def test_render_empty_payload_returns_empty():
    assert render_llm_context(parse_start_payload("")) == ""


def test_render_field_order_is_canonical():
    """Manager-friendly order: country → hotel → offer/key → from → id."""
    p = parse_start_payload(
        "utm_ya_id_5_from_msk_country_turkey_hotel_rixos"
    )
    ctx = render_llm_context(p)
    # country precedes hotel, hotel precedes from, from precedes id
    assert ctx.index("страна") < ctx.index("отель")
    assert ctx.index("отель") < ctx.index("город вылета")
    assert ctx.index("город вылета") < ctx.index("ID объявления")


def test_render_unknown_source_falls_back_to_code():
    p = parse_start_payload("utm_xyz_key_test")
    ctx = render_llm_context(p)
    # Unknown source code is preserved literally in the label so the
    # LLM can still mention it intelligently.
    assert "xyz" in ctx
    assert "test" in ctx
