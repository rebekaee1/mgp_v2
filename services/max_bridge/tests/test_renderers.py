from app.renderers import (
    _format_date_short,
    _format_meal,
    _format_pax,
    _format_price,
    _format_rating,
    _format_stars,
    _md_escape,
    render_final_menu_keyboard,
    render_final_menu_text,
    render_tour_card_caption,
    render_tour_card_keyboard,
    render_welcome_after_reset,
)


# ── helpers ────────────────────────────────────────────────────────────


def test_md_escape_handles_specials():
    assert _md_escape("Hotel *5* [VIP]") == r"Hotel \*5\* \[VIP\]"


def test_md_escape_handles_empty_and_none():
    assert _md_escape("") == ""
    assert _md_escape(None) == ""


def test_format_stars_clamps():
    assert _format_stars(5) == "⭐⭐⭐⭐⭐"
    assert _format_stars(0) == ""
    assert _format_stars(7) == "⭐⭐⭐⭐⭐"
    assert _format_stars(None) == ""
    assert _format_stars("3") == "⭐⭐⭐"
    assert _format_stars("abc") == ""


def test_format_rating_one_decimal():
    assert _format_rating(9.4) == "9.4"
    assert _format_rating(0) == ""
    assert _format_rating(None) == ""
    assert _format_rating(9.0) == "9"


def test_format_price_thin_space():
    assert _format_price(410000) == "410 000 ₽"
    assert _format_price(0) == ""
    assert _format_price(None) == ""
    assert _format_price("abc") == ""


def test_format_date_short_strips_year():
    assert _format_date_short("18.05.2026") == "18.05"
    assert _format_date_short("") == ""
    assert _format_date_short(None) == ""
    assert _format_date_short("2026-05-18") == "2026-05-18"


def test_format_meal_uses_description_first():
    assert _format_meal({"meal_description": "Всё включено", "food_type": "BB"}) == "Всё включено"
    assert _format_meal({"meal_description": "", "food_type": "AI"}) == "Всё включено"
    assert _format_meal({"meal_description": "", "food_type": "ZZ"}) == "ZZ"
    assert _format_meal({}) == ""


def test_format_pax_declension():
    # _format_pax now labels the TOTAL party size (adults + children),
    # so 5+ reads "за N человек" rather than the old adults-only wording.
    assert _format_pax(1) == "за одного"
    assert _format_pax(2) == "за двоих"
    assert _format_pax(3) == "за троих"
    assert _format_pax(4) == "за четверых"
    assert _format_pax(5) == "за 5 человек"
    assert _format_pax(0) == ""
    assert _format_pax(None) == ""


def test_format_composition():
    from app.renderers import _format_composition
    assert _format_composition(2, 0) == "2 взрослых"
    assert _format_composition(1, 0) == "1 взрослый"
    assert _format_composition(2, 1) == "2 взрослых + 1 ребёнок"
    assert _format_composition(2, 2) == "2 взрослых + 2 ребёнка"
    assert _format_composition(1, 3) == "1 взрослый + 3 ребёнка"
    assert _format_composition(2, 5) == "2 взрослых + 5 детей"
    assert _format_composition(0, 0) == ""


# ── caption ────────────────────────────────────────────────────────────


_HAPPY_CARD = {
    "hotel_name": "Crystal Sunrise Queen Luxury",
    "hotel_stars": 5,
    "hotel_rating": 9.4,
    "country": "Турция",
    "resort": "Сиде",
    "region": "Сиде",
    "date_from": "18.05.2026",
    "date_to": "25.05.2026",
    "nights": 7,
    "price": 410000,
    "adults": 2,
    "meal_description": "Всё включено",
    "room_type": "Standard Double",
    "flight_included": True,
    "is_hotel_only": False,
    "departure_city": "Москва",
    "operator": "Pegas",
    "image_url": "https://tourvisor.example/pic.jpg",
    "hotel_link": "https://mgp.ru/tours/#tvtourid=12345",
    "id": "12345",
}


def test_caption_includes_all_core_fields():
    text = render_tour_card_caption(_HAPPY_CARD)
    for needle in [
        "Crystal Sunrise Queen Luxury",
        "⭐⭐⭐⭐⭐",
        "9.4",
        "Турция",
        "Сиде",
        "18.05 → 25.05",
        "7 ночей",
        "Всё включено",
        "Standard Double",
        "✈️ Перелёт включён",
        "Москва",
        "410 000 ₽",
        "за двоих",
    ]:
        assert needle in text, f"missing {needle!r} in caption:\n{text}"


def test_caption_never_exposes_operator_name():
    """Regression: operator/supplier names are internal — keep them out of the user-visible caption.

    Renderers must not surface supplier names like Pegas / Coral / Anex etc.
    even when present in the source tour_card dict from the backend.
    """
    card = dict(_HAPPY_CARD)
    card["operator"] = "Pegas"
    text = render_tour_card_caption(card)
    for forbidden in ("Pegas", "Coral", "Anex", "Турплатформа", "оператор"):
        assert forbidden not in text, f"caption leaked supplier name {forbidden!r}:\n{text}"


def test_caption_truncated_when_pathological():
    long_card = {"hotel_name": "X" * 9000, "country": "Турция"}
    text = render_tour_card_caption(long_card)
    assert len(text) <= 3901
    assert text.endswith("…")


def test_caption_hotel_only_swap():
    card = {
        "hotel_name": "Hotel Only",
        "is_hotel_only": True,
        "flight_included": False,
        "country": "Турция",
    }
    text = render_tour_card_caption(card)
    assert "🏨 Только отель" in text
    assert "✈️" not in text


def test_caption_escapes_user_markdown_specials():
    card = {"hotel_name": "Hotel *Special* [VIP]"}
    text = render_tour_card_caption(card)
    # The hotel-name line still wraps the (escaped) name in *...* for bold,
    # but the inner stars must be backslash-escaped so they don't toggle bold.
    assert r"\*Special\*" in text
    assert r"\[VIP\]" in text


def test_caption_no_country_resort_dup():
    card = {"hotel_name": "Hotel", "country": "Россия", "resort": "Россия"}
    text = render_tour_card_caption(card)
    # 'Россия' must not appear twice next to each other
    assert text.count("Россия") == 1


def test_caption_no_price_when_zero():
    card = {"hotel_name": "Hotel", "price": 0, "adults": 2}
    text = render_tour_card_caption(card)
    assert "₽" not in text


# ── keyboard ───────────────────────────────────────────────────────────


def test_keyboard_link_button_for_valid_url():
    kb = render_tour_card_keyboard(_HAPPY_CARD)
    assert kb is not None
    assert kb["type"] == "inline_keyboard"
    btn = kb["payload"]["buttons"][0][0]
    assert btn["type"] == "link"
    assert btn["url"] == "https://mgp.ru/tours/#tvtourid=12345"
    assert "Забронировать" in btn["text"]


def test_keyboard_returns_none_for_invalid_links():
    assert render_tour_card_keyboard({"hotel_link": ""}) is None
    assert render_tour_card_keyboard({"hotel_link": "javascript:alert(1)"}) is None
    assert render_tour_card_keyboard({"hotel_link": "/relative/path"}) is None
    assert render_tour_card_keyboard({}) is None


def test_keyboard_rejects_oversize_link():
    overlong = "https://example.com/" + "a" * 2050
    assert render_tour_card_keyboard({"hotel_link": overlong}) is None


# ── final menu ─────────────────────────────────────────────────────────


def test_final_menu_text_short():
    text = render_final_menu_text()
    assert text and len(text) < 100


def test_final_menu_keyboard_only_message_type():
    kb = render_final_menu_keyboard()
    assert kb["type"] == "inline_keyboard"
    rows = kb["payload"]["buttons"]
    assert len(rows) >= 1
    flat = [btn for row in rows for btn in row]
    assert flat, "menu must have buttons"
    for btn in flat:
        assert btn["type"] == "message", f"final-menu must use message type, got {btn['type']}"
        assert btn.get("text"), "menu button must have text"
        assert btn.get("payload"), "menu button must have payload"


def test_final_menu_layout_two_plus_one():
    """Two refine buttons in row 1, the per-flight specialisation alone in row 2.

    Lets MAX render full button labels on a narrow viewport (3-up rows
    truncate text on mobile).
    """
    kb = render_final_menu_keyboard()
    rows = kb["payload"]["buttons"]
    assert len(rows) == 2
    assert len(rows[0]) == 2
    assert len(rows[1]) == 1


def test_final_menu_has_three_card_anchored_actions():
    """v2 menu: details + show-more + flight; no shopping cues (Cheaper/Better)."""
    kb = render_final_menu_keyboard()
    flat = [btn for row in kb["payload"]["buttons"] for btn in row]
    texts = {btn["text"] for btn in flat}
    payloads = {btn["payload"] for btn in flat}

    # Exact set — guards against accidental future additions/removals.
    assert texts == {"🔍 Уточнить детали", "📋 Показать ещё", "✈️ Уточнить перелёт"}

    # Payloads must match the wording learnt by system_prompt.md so the
    # assistant routes them to the correct behaviour without magic.
    assert payloads == {
        "уточнить детали по варианту",
        "покажи ещё",
        "уточнить перелёт по варианту",
    }


def test_final_menu_dropped_legacy_shopping_buttons():
    """Регрессия: «Подешевле» / «Получше звёзды» из v1 не должны вернуться."""
    kb = render_final_menu_keyboard()
    flat = [btn for row in kb["payload"]["buttons"] for btn in row]
    texts = " | ".join(b["text"] for b in flat)
    payloads = " | ".join(b["payload"] for b in flat)
    for forbidden in ("Подешевле", "Получше", "подешевле", "звёздностью"):
        assert forbidden not in texts, f"legacy button text returned: {forbidden}"
        assert forbidden not in payloads, f"legacy payload returned: {forbidden}"


# ── welcome after reset ────────────────────────────────────────────────


def test_welcome_after_reset_short_and_meaningful():
    text = render_welcome_after_reset()
    assert text
    assert len(text) < 200
    # Must explicitly signal a fresh start to the user.
    assert "чистого листа" in text or "заново" in text
    # Must prompt the user for the next step (avoid a dead-end message).
    assert "?" in text
