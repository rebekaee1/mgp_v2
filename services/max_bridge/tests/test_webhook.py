import asyncio
from typing import Any

import httpx
import pytest
from fakeredis import aioredis as fake_aioredis
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.chat_proxy import ChatProxy, ChatResponse
from app.config import Settings
from app.session_store import SessionStore
from app.webhook import _extract_message, _resolve_tenant, router


def _settings(*, token: str = "bot-token", secret: str = "hook-secret") -> Settings:
    return Settings(
        max_bot_token_mgp_tour=token,
        max_webhook_secret_mgp_tour=secret,
        max_default_assistant_id="00000000-0000-0000-0000-000000000001",
        max_redis_url="redis://localhost/15",
        max_session_ttl_seconds=60,
        max_backend_internal_url="http://backend:8080",
    )


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
        max_webhook_secret_mgp_tour="",  # explicit empty — partial config
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


@pytest.fixture
def app_under_test(monkeypatch: pytest.MonkeyPatch):
    sent_messages: list[dict[str, Any]] = []

    class _StubChatProxy:
        async def chat(self, *, message: str, session_id: str, assistant_id: str):
            return ChatResponse(reply=f"echo: {message}", tour_cards=[], conversation_id=session_id)

        async def aclose(self) -> None:
            pass

    async def _fake_send(self, **kwargs):
        sent_messages.append(kwargs)
        return {"ok": True}

    async def _fake_aclose(self):
        pass

    async def _fake_aenter(self):
        return self

    async def _fake_aexit(self, *exc):
        return None

    monkeypatch.setattr("app.webhook.MaxApiClient.send_text", _fake_send)
    monkeypatch.setattr("app.webhook.MaxApiClient.aclose", _fake_aclose)
    monkeypatch.setattr("app.webhook.MaxApiClient.__aenter__", _fake_aenter)
    monkeypatch.setattr("app.webhook.MaxApiClient.__aexit__", _fake_aexit)

    settings = _settings(token="test-token")
    app = FastAPI()
    app.state.settings = settings
    app.state.chat_proxy = _StubChatProxy()
    app.state.session_store = SessionStore(
        fake_aioredis.FakeRedis(decode_responses=True), ttl_seconds=60
    )
    app.include_router(router)
    return app, sent_messages


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
    # The background task is scheduled on the event loop; let it run.
    loop = asyncio.get_event_loop()
    loop.run_until_complete(asyncio.sleep(0.05))
    assert sent_messages, "background task must call MAX send_text"
    assert sent_messages[0]["text"].startswith("echo: привет")


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
