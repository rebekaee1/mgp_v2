"""Tests for RuntimeMetadataClient (welcome_message fetcher with Redis cache)."""

import pytest
import respx
from fakeredis import aioredis as fake_aioredis

from app.runtime_meta import RuntimeMetadataClient


def _metadata_payload(welcome: str | None) -> dict:
    return {
        "tenant": {
            "assistant_id": "00000000-0000-0000-0000-000000000001",
            "branding": {
                "title": "AI Ассистент",
                "subtitle": "Турагентство",
                "primary_color": "#E30613",
                "welcome_message": welcome,
            },
        },
    }


@pytest.fixture
def redis_client():
    return fake_aioredis.FakeRedis(decode_responses=True)


def _make_client(redis_client) -> RuntimeMetadataClient:
    return RuntimeMetadataClient(
        backend_url="http://backend.test:8080",
        redis_client=redis_client,
        service_token="test-token",
        cache_ttl_seconds=60,
        request_timeout=2.0,
    )


@pytest.mark.asyncio
async def test_get_welcome_returns_text_when_backend_responds(redis_client):
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("http://backend.test:8080/api/runtime/metadata").respond(
            200, json=_metadata_payload("Здравствуйте! Я Анна из МГП Тур.")
        )
        client = _make_client(redis_client)
        result = await client.get_welcome_message("aid-123")
        assert result == "Здравствуйте! Я Анна из МГП Тур."
        # The service token must be forwarded so backend can flip to strict
        # auth later without bridge redeployment.
        last = route.calls.last
        assert last.request.headers.get("x-mgp-service-token") == "test-token"
        assert last.request.headers.get("x-assistant-id") == "aid-123"


@pytest.mark.asyncio
async def test_get_welcome_returns_none_when_field_empty(redis_client):
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("http://backend.test:8080/api/runtime/metadata").respond(
            200, json=_metadata_payload(welcome=None)
        )
        client = _make_client(redis_client)
        assert await client.get_welcome_message("aid-empty") is None


@pytest.mark.asyncio
async def test_get_welcome_returns_none_when_empty_string(redis_client):
    """Whitespace-only welcome from dashboard should be treated as missing."""
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("http://backend.test:8080/api/runtime/metadata").respond(
            200, json=_metadata_payload(welcome="   \n  ")
        )
        client = _make_client(redis_client)
        assert await client.get_welcome_message("aid-ws") is None


@pytest.mark.asyncio
async def test_get_welcome_cached_avoids_second_http_call(redis_client):
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("http://backend.test:8080/api/runtime/metadata").respond(
            200, json=_metadata_payload("Привет!")
        )
        client = _make_client(redis_client)
        first = await client.get_welcome_message("aid-cache")
        second = await client.get_welcome_message("aid-cache")
        assert first == second == "Привет!"
        assert len(route.calls) == 1, "second call must come from Redis cache"


@pytest.mark.asyncio
async def test_get_welcome_negative_cache_for_empty_dashboard(redis_client):
    """Even when welcome is empty in dashboard, we cache the miss so we don't
    spam the backend on every bot_started."""
    async with respx.mock(assert_all_called=False) as mock:
        route = mock.get("http://backend.test:8080/api/runtime/metadata").respond(
            200, json=_metadata_payload(welcome=None)
        )
        client = _make_client(redis_client)
        await client.get_welcome_message("aid-neg")
        await client.get_welcome_message("aid-neg")
        assert len(route.calls) == 1
        # The cache value must be the sentinel, not an empty string.
        keys = await redis_client.keys("max:welcome:*")
        assert keys == ["max:welcome:aid-neg"]


@pytest.mark.asyncio
async def test_get_welcome_returns_none_on_backend_5xx(redis_client):
    async with respx.mock(assert_all_called=False) as mock:
        mock.get("http://backend.test:8080/api/runtime/metadata").respond(503, text="busy")
        client = _make_client(redis_client)
        assert await client.get_welcome_message("aid-5xx") is None


@pytest.mark.asyncio
async def test_get_welcome_returns_none_on_network_error(redis_client):
    """If backend is unreachable (Docker network blip), bridge stays up and
    falls back to a hardcoded greeting at the caller."""
    import httpx

    async with respx.mock(assert_all_called=False) as mock:
        mock.get("http://backend.test:8080/api/runtime/metadata").mock(
            side_effect=httpx.ConnectError("no route to host")
        )
        client = _make_client(redis_client)
        assert await client.get_welcome_message("aid-net") is None


@pytest.mark.asyncio
async def test_get_welcome_empty_assistant_id_short_circuits(redis_client):
    client = _make_client(redis_client)
    assert await client.get_welcome_message("") is None
    assert await client.get_welcome_message(None) is None  # type: ignore[arg-type]
