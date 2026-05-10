import asyncio
from typing import Any

import pytest
from fakeredis import aioredis as fake_aioredis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat_proxy import ChatResponse
from app.config import Settings
from app.image_cache import ImageCache
from app.max_api import MaxApiError
from app.session_store import SessionStore
from app.webhook import _extract_message, _resolve_tenant, router


def _settings(*, token: str = "bot-token", secret: str = "hook-secret",
              render_tour_cards: bool = True, tour_cards_limit: int = 3) -> Settings:
    return Settings(
        max_bot_token_mgp_tour=token,
        max_webhook_secret_mgp_tour=secret,
        max_default_assistant_id="00000000-0000-0000-0000-000000000001",
        max_redis_url="redis://localhost/15",
        max_session_ttl_seconds=60,
        max_backend_internal_url="http://backend:8080",
        max_render_tour_cards=render_tour_cards,
        max_tour_cards_limit=tour_cards_limit,
    )


# ── pure-function tests ────────────────────────────────────────────────


def test_resolve_tenant_matches_correct_secret():
    settings = _settings(secret="good-secret")
    tenant = _resolve_tenant(settings, "good-secret")
    assert tenant is not None
    assert tenant.slug == "mgp-tour"


def test_resolve_tenant_rejects_unknown_secret():
    settings = _settings(secret="good-secret")
    assert _resolve_tenant(settings, "bad-secret") is None
    assert _resolve_tenant(settings, None) is None
    assert _resolve_tenant(settings, "") is None


def test_tenant_skipped_if_secret_missing():
    settings = Settings(
        max_bot_token_mgp_tour="bot-token",
        max_webhook_secret_mgp_tour="",
    )
    assert settings.tenant_bindings() == []


def test_extract_message_handles_message_created():
    update = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 12345},
            "recipient": {"chat_id": 999},
            "body": {"text": "  Турция в июне  "},
        },
    }
    parsed = _extract_message(update)
    assert parsed == {"user_id": 12345, "chat_id": 999, "text": "Турция в июне"}


def test_extract_message_returns_none_for_other_updates():
    assert _extract_message({"update_type": "message_callback"}) is None
    assert _extract_message({"update_type": "message_created", "message": {}}) is None
    assert _extract_message({"update_type": "message_created", "message": {"body": {"text": "  "}}}) is None


# ── fixtures ───────────────────────────────────────────────────────────


def _sample_cards(n: int = 5) -> list[dict[str, Any]]:
    """Build N realistic tour cards in the same shape mgp-backend returns."""
    return [
        {
            "hotel_name": f"Hotel {i}",
            "hotel_stars": 5,
            "hotel_rating": 9.0 + i * 0.1,
            "country": "Турция",
            "resort": "Сиде",
            "region": "Сиде",
            "date_from": "18.05.2026",
            "date_to": "25.05.2026",
            "nights": 7,
            "price": 400000 + i * 10000,
            "adults": 2,
            "meal_description": "Всё включено",
            "room_type": "Standard Double",
            "flight_included": True,
            "departure_city": "Москва",
            "operator": "Pegas",
            "image_url": f"https://tourvisor.test/img{i}.jpg",
            "hotel_link": f"https://mgp.ru/tours/#tvtourid={1000 + i}",
            "id": str(1000 + i),
        }
        for i in range(1, n + 1)
    ]


def _build_app(*, settings: Settings, tour_cards: list[dict[str, Any]],
               sent_messages: list[dict[str, Any]]) -> FastAPI:
    class _StubChatProxy:
        async def chat(self, *, message: str, session_id: str, assistant_id: str):
            return ChatResponse(
                reply=f"reply: {message}",
                tour_cards=list(tour_cards),
                conversation_id=session_id,
            )

        async def aclose(self) -> None:
            pass

    app = FastAPI()
    app.state.settings = settings
    app.state.chat_proxy = _StubChatProxy()
    app.state.session_store = SessionStore(
        fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60
    )
    app.state.image_cache = ImageCache(
        fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60
    )
    app.include_router(router)
    return app


def _patch_max_client(monkeypatch: pytest.MonkeyPatch, sent_messages: list[dict[str, Any]],
                     *, fail_first_n: int = 0) -> list[int]:
    """Replace MaxApiClient methods so we can capture every outbound call.

    ``fail_first_n`` lets a test simulate transient send_message failures.
    Returns a mutable counter list we can use to inspect attempts later.
    """
    attempts = [0]

    async def _fake_send_message(self, **kwargs):
        attempts[0] += 1
        if attempts[0] <= fail_first_n:
            raise MaxApiError(400, "test.failure", "simulated", {})
        sent_messages.append(kwargs)
        return {"ok": True}

    async def _fake_aclose(self): pass
    async def _fake_aenter(self): return self
    async def _fake_aexit(self, *exc): return None

    monkeypatch.setattr("app.webhook.MaxApiClient.send_message", _fake_send_message)
    monkeypatch.setattr("app.webhook.MaxApiClient.aclose", _fake_aclose)
    monkeypatch.setattr("app.webhook.MaxApiClient.__aenter__", _fake_aenter)
    monkeypatch.setattr("app.webhook.MaxApiClient.__aexit__", _fake_aexit)
    return attempts


@pytest.fixture
def app_under_test(monkeypatch: pytest.MonkeyPatch):
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)
    app = _build_app(settings=_settings(token="test-token"), tour_cards=[],
                     sent_messages=sent_messages)
    return app, sent_messages


# ── basic webhook lifecycle ────────────────────────────────────────────


def test_webhook_unauthorized(app_under_test):
    app, _ = app_under_test
    client = TestClient(app)
    response = client.post("/max/webhook", json={"update_type": "message_created"})
    assert response.status_code == 401


def test_webhook_accepts_valid_request_and_processes_in_background(app_under_test):
    app, sent_messages = app_under_test
    client = TestClient(app)
    update = {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": 7},
            "recipient": {"chat_id": 7},
            "body": {"text": "привет"},
        },
    }
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=update,
    )
    assert response.status_code == 200
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0.1))
    assert sent_messages, "background task must call MAX send_message"
    assert sent_messages[0]["text"].startswith("reply: привет")


def test_webhook_silently_drops_unhandled_updates(app_under_test):
    app, sent_messages = app_under_test
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json={"update_type": "message_callback"},
    )
    assert response.status_code == 200
    assert sent_messages == []


# ── tour-card integration tests ────────────────────────────────────────


def _send_message_event(text: str, user_id: int = 7) -> dict[str, Any]:
    return {
        "update_type": "message_created",
        "message": {
            "sender": {"user_id": user_id},
            "recipient": {"chat_id": user_id},
            "body": {"text": text},
        },
    }


def test_webhook_renders_three_tour_cards_with_photos_and_final_menu(monkeypatch):
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)

    async def _fake_resolve_image_token(**kwargs):
        return "MEDIA_TOK"
    monkeypatch.setattr("app.webhook._resolve_image_token", _fake_resolve_image_token)

    cards = _sample_cards(5)
    app = _build_app(
        settings=_settings(token="test-token", render_tour_cards=True, tour_cards_limit=3),
        tour_cards=cards,
        sent_messages=sent_messages,
    )
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_send_message_event("Турция, май"),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.3))

    # Expect: 1 reply text + 3 photo cards + 1 final menu = 5 sent messages
    assert len(sent_messages) == 5, sent_messages
    # The reply chunk goes first.
    assert sent_messages[0]["text"].startswith("reply:")
    # Cards 2..4 must each carry an image and a keyboard.
    for i in range(1, 4):
        msg = sent_messages[i]
        attachments = msg.get("attachments") or []
        types = [a["type"] for a in attachments]
        assert "image" in types, f"card #{i} missing image attachment: {msg}"
        assert "inline_keyboard" in types, f"card #{i} missing keyboard: {msg}"
        image = next(a for a in attachments if a["type"] == "image")
        assert image["payload"]["token"] == "MEDIA_TOK"
        kb_buttons = next(a for a in attachments if a["type"] == "inline_keyboard")["payload"]["buttons"]
        link_btn = kb_buttons[0][0]
        assert link_btn["type"] == "link"
        assert link_btn["url"].startswith("https://mgp.ru/tours/")
    # Final menu uses message-type buttons.
    final = sent_messages[4]
    assert "Что дальше" in final["text"]
    final_kb = final["attachments"][0]
    assert final_kb["type"] == "inline_keyboard"
    flat = [b for row in final_kb["payload"]["buttons"] for b in row]
    assert all(b["type"] == "message" for b in flat)


def test_webhook_does_not_render_cards_when_flag_disabled(monkeypatch):
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)

    async def _fake_resolve_image_token(**kwargs):
        # Should never be called because flag is off.
        raise AssertionError("image upload must not be attempted when flag is off")
    monkeypatch.setattr("app.webhook._resolve_image_token", _fake_resolve_image_token)

    cards = _sample_cards(3)
    app = _build_app(
        settings=_settings(token="test-token", render_tour_cards=False),
        tour_cards=cards,
        sent_messages=sent_messages,
    )
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_send_message_event("Турция"),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.2))

    # Only the reply chunk is sent — no photo cards, no final menu.
    assert len(sent_messages) == 1
    assert sent_messages[0]["text"].startswith("reply:")
    assert not sent_messages[0].get("attachments")


def test_webhook_falls_back_to_text_only_card_when_image_upload_fails(monkeypatch):
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)

    async def _fake_resolve_image_token(**kwargs):
        return None  # simulate image fetch / upload failure
    monkeypatch.setattr("app.webhook._resolve_image_token", _fake_resolve_image_token)

    cards = _sample_cards(3)
    app = _build_app(
        settings=_settings(token="test-token", render_tour_cards=True, tour_cards_limit=3),
        tour_cards=cards,
        sent_messages=sent_messages,
    )
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_send_message_event("Турция"),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.3))

    # Still 1 reply + 3 cards + 1 final menu — but cards have no image attachment.
    assert len(sent_messages) == 5
    for i in range(1, 4):
        msg = sent_messages[i]
        attachments = msg.get("attachments") or []
        types = [a["type"] for a in attachments]
        assert "image" not in types, f"card #{i} unexpectedly has an image: {msg}"
        # The booking-link keyboard must still be present.
        assert "inline_keyboard" in types, f"card #{i} missing keyboard: {msg}"
