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
from app.webhook import _extract_message, _is_reset_command, _resolve_tenant, router


class _FakeRuntimeMeta:
    """Minimal in-memory stand-in for RuntimeMetadataClient.

    Tests control what welcome to return via ``welcome``; ``calls`` counts
    fetches so tests can assert cache hits / single fetch per event.
    """

    def __init__(self, welcome: str | None = None) -> None:
        self.welcome = welcome
        self.calls = 0

    async def get_welcome_message(self, assistant_id: str):
        self.calls += 1
        return self.welcome

    async def aclose(self) -> None:
        pass


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
    assert parsed == {"event": "message", "user_id": 12345, "chat_id": 999, "text": "Турция в июне"}


def test_extract_message_returns_none_for_other_updates():
    assert _extract_message({"update_type": "message_callback"}) is None
    assert _extract_message({"update_type": "message_created", "message": {}}) is None
    assert _extract_message({"update_type": "message_created", "message": {"body": {"text": "  "}}}) is None


def test_extract_message_handles_bot_started_user_shape():
    """MAX sends bot_started with `user` block (real payload from prod)."""
    update = {
        "update_type": "bot_started",
        "chat_id": 555,
        "user": {"user_id": 12345, "name": "Иван"},
        "timestamp": 1778411500000,
    }
    parsed = _extract_message(update)
    assert parsed == {"event": "bot_started", "user_id": 12345, "chat_id": 555}


def test_extract_message_handles_bot_started_sender_shape():
    """Tolerant of an alternate payload where the user lives under `sender`."""
    update = {
        "update_type": "bot_started",
        "chat_id": 1,
        "sender": {"user_id": 42},
    }
    parsed = _extract_message(update)
    assert parsed == {"event": "bot_started", "user_id": 42, "chat_id": 1}


def test_extract_message_bot_started_without_user_returns_none():
    assert _extract_message({"update_type": "bot_started", "chat_id": 1}) is None


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
               sent_messages: list[dict[str, Any]],
               welcome: str | None = None) -> FastAPI:
    class _StubChatProxy:
        async def chat(self, *, message: str, session_id: str, assistant_id: str, **kwargs):
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
    app.state.runtime_meta = _FakeRuntimeMeta(welcome=welcome)
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


# ── _is_reset_command unit tests ───────────────────────────────────────


@pytest.mark.parametrize("text", [
    "/restart", "/new", "/start", "/reset",
    "/Restart", "/RESET", " /restart ",
])
def test_is_reset_command_slash_commands_match(text):
    assert _is_reset_command(text) is True


@pytest.mark.parametrize("text", [
    "/start 12345",     # deep-link with arg
    "/restart please",  # extra wording
    "/foo", "/bar",     # unrelated commands
])
def test_is_reset_command_slash_with_args_rejected(text):
    assert _is_reset_command(text) is False


@pytest.mark.parametrize("text", [
    "начать заново",
    "Начать заново",
    "Начать заново.",
    "начать заново!",
    "новый диалог",
    "новый чат",
    "сброс",
    "сбросить диалог",
    "сбрось диалог",
    "сбрось чат",
    "обнули контекст",
    "обнулить диалог",
    "забудь всё",
    "Забудь всё.",
    "забудь все",      # without ё
    "ЗАБУДЬ ВСЁ!",
    "reset",
    "Restart",
    "начнём сначала",
    "начнем заново",
])
def test_is_reset_command_russian_phrases_match(text):
    assert _is_reset_command(text) is True, f"should match: {text!r}"


@pytest.mark.parametrize("text", [
    "",
    "   ",
    "забудь всё что я говорил и подбери Турцию",  # partial — NOT a full match
    "хочу начать заново планирование",
    "сбрось мне варианты подешевле",
    "новый диалог про Египет",
    "Турция, май, до 200к",
    "/start с балкона",
    "покажи ещё",
    "уточнить детали по варианту",
])
def test_is_reset_command_rejects_non_reset_messages(text):
    assert _is_reset_command(text) is False, f"should NOT match: {text!r}"


# ── reset flow integration ─────────────────────────────────────────────


def test_webhook_reset_command_wipes_session_and_replies_welcome(monkeypatch):
    """End-to-end: pre-seed a session, send /restart → session erased, welcome sent, chat_proxy NOT called.

    The welcome text comes from the dashboard (RuntimeMetadataClient). When
    the stub returns None — the default greeting is used.
    """
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)

    chat_proxy_calls = [0]

    class _CountingChatProxy:
        async def chat(self, *, message, session_id, assistant_id, **kwargs):
            chat_proxy_calls[0] += 1
            return ChatResponse(reply="should not be called", tour_cards=[], conversation_id=session_id)

        async def aclose(self):
            pass

    app = FastAPI()
    app.state.settings = _settings(token="test-token")
    app.state.chat_proxy = _CountingChatProxy()
    redis = fake_aioredis.FakeRedis(decode_responses=True)
    app.state.session_store = SessionStore(redis, ttl_seconds=60)
    app.state.image_cache = ImageCache(fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60)
    app.state.runtime_meta = _FakeRuntimeMeta(welcome=None)  # → fallback default
    app.include_router(router)

    user_id = 4242
    loop = asyncio.get_event_loop()
    loop.run_until_complete(app.state.session_store.get_or_create_session(user_id))
    assert loop.run_until_complete(app.state.session_store.get_session(user_id)) is not None

    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_send_message_event("/restart", user_id=user_id),
    )
    assert response.status_code == 200
    loop.run_until_complete(asyncio.sleep(0.1))

    assert loop.run_until_complete(app.state.session_store.get_session(user_id)) is None
    assert chat_proxy_calls[0] == 0
    assert len(sent_messages) == 1
    welcome = sent_messages[0]
    # Fallback greeting (welcome=None from dashboard).
    assert "ИИ-ассистент" in welcome["text"] or "Куда хотите" in welcome["text"]
    assert not welcome.get("attachments")


def test_webhook_reset_command_uses_dashboard_welcome_when_set(monkeypatch):
    """If the dashboard has a welcome_message, /restart uses it verbatim."""
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)

    chat_proxy_calls = [0]

    class _CountingChatProxy:
        async def chat(self, *, message, session_id, assistant_id, **kwargs):
            chat_proxy_calls[0] += 1
            return ChatResponse(reply="x", tour_cards=[], conversation_id=session_id)

        async def aclose(self): pass

    custom_welcome = "Привет! Я Анна из МГП Тур. Куда едем?"
    app = FastAPI()
    app.state.settings = _settings(token="test-token")
    app.state.chat_proxy = _CountingChatProxy()
    app.state.session_store = SessionStore(fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60)
    app.state.image_cache = ImageCache(fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60)
    app.state.runtime_meta = _FakeRuntimeMeta(welcome=custom_welcome)
    app.include_router(router)

    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_send_message_event("/restart"),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
    assert chat_proxy_calls[0] == 0
    assert len(sent_messages) == 1
    assert sent_messages[0]["text"] == custom_welcome
    assert app.state.runtime_meta.calls == 1


def _bot_started_event(user_id: int = 7, chat_id: int = 7) -> dict[str, Any]:
    return {
        "update_type": "bot_started",
        "chat_id": chat_id,
        "user": {"user_id": user_id, "name": "Test"},
        "timestamp": 1778411500000,
    }


def test_webhook_bot_started_sends_dashboard_welcome(monkeypatch):
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)

    custom_welcome = "Здравствуйте! Чем помочь?"
    app = _build_app(
        settings=_settings(token="test-token"),
        tour_cards=[],
        sent_messages=sent_messages,
        welcome=custom_welcome,
    )
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_bot_started_event(),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
    assert len(sent_messages) == 1
    assert sent_messages[0]["text"] == custom_welcome
    assert not sent_messages[0].get("attachments")


def test_webhook_bot_started_falls_back_to_default_when_dashboard_empty(monkeypatch):
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)
    app = _build_app(
        settings=_settings(token="test-token"),
        tour_cards=[],
        sent_messages=sent_messages,
        welcome=None,
    )
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_bot_started_event(),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
    assert len(sent_messages) == 1
    assert "ИИ-ассистент" in sent_messages[0]["text"]


def test_webhook_welcome_kill_switch_skips_dashboard_call(monkeypatch):
    """MAX_WELCOME_FROM_BACKEND=0 → bridge does not even try to fetch dashboard."""
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)

    settings = _settings(token="test-token")
    settings.max_welcome_from_backend = False  # type: ignore[attr-defined]

    app = _build_app(
        settings=settings,
        tour_cards=[],
        sent_messages=sent_messages,
        welcome="should-not-be-used",
    )
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_bot_started_event(),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
    assert app.state.runtime_meta.calls == 0, "kill-switch must short-circuit the fetch"
    assert len(sent_messages) == 1
    assert "ИИ-ассистент" in sent_messages[0]["text"]


@pytest.mark.parametrize("trigger", [
    "забудь всё",
    "Начать заново.",
    "новый диалог",
    "/new",
])
def test_webhook_reset_triggers_for_multiple_phrasings(monkeypatch, trigger):
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)
    chat_proxy_calls = [0]

    class _CountingChatProxy:
        async def chat(self, *, message, session_id, assistant_id, **kwargs):
            chat_proxy_calls[0] += 1
            return ChatResponse(reply="x", tour_cards=[], conversation_id=session_id)

        async def aclose(self):
            pass

    app = FastAPI()
    app.state.settings = _settings(token="test-token")
    app.state.chat_proxy = _CountingChatProxy()
    app.state.session_store = SessionStore(
        fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60
    )
    app.state.image_cache = ImageCache(
        fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60
    )
    app.state.runtime_meta = _FakeRuntimeMeta(welcome=None)
    app.include_router(router)

    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_send_message_event(trigger),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.05))

    assert chat_proxy_calls[0] == 0, f"chat_proxy must NOT be called for trigger={trigger!r}"
    assert len(sent_messages) == 1
    # With welcome=None the bridge uses the fallback default text.
    assert "ИИ-ассистент" in sent_messages[0]["text"] or "Куда хотите" in sent_messages[0]["text"]


def test_webhook_normal_message_still_calls_chat_proxy(monkeypatch):
    """Sanity guard: free-form text routes to the backend (no false reset)."""
    sent_messages: list[dict[str, Any]] = []
    _patch_max_client(monkeypatch, sent_messages)
    app = _build_app(settings=_settings(token="test-token"), tour_cards=[],
                     sent_messages=sent_messages)
    client = TestClient(app)
    response = client.post(
        "/max/webhook",
        headers={"X-Max-Bot-Api-Secret": "hook-secret"},
        json=_send_message_event("Турция, май"),
    )
    assert response.status_code == 200
    asyncio.get_event_loop().run_until_complete(asyncio.sleep(0.1))
    assert any(m["text"].startswith("reply:") for m in sent_messages)
