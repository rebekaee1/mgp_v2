import pytest
from fakeredis import aioredis as fake_aioredis

from app.image_cache import ImageCache


@pytest.fixture
def redis_client():
    return fake_aioredis.FakeRedis(decode_responses=True)


@pytest.mark.asyncio
async def test_get_returns_none_when_missing(redis_client):
    cache = ImageCache(redis_client, ttl_seconds=60)
    assert await cache.get("https://example.com/image.jpg") is None


@pytest.mark.asyncio
async def test_set_then_get_returns_token(redis_client):
    cache = ImageCache(redis_client, ttl_seconds=60)
    await cache.set("https://example.com/image.jpg", "TOKEN_ABC")
    assert await cache.get("https://example.com/image.jpg") == "TOKEN_ABC"


@pytest.mark.asyncio
async def test_different_urls_isolated(redis_client):
    cache = ImageCache(redis_client, ttl_seconds=60)
    await cache.set("https://a.example/x.jpg", "TOK_A")
    await cache.set("https://b.example/y.jpg", "TOK_B")
    assert await cache.get("https://a.example/x.jpg") == "TOK_A"
    assert await cache.get("https://b.example/y.jpg") == "TOK_B"


@pytest.mark.asyncio
async def test_empty_inputs_are_safe(redis_client):
    cache = ImageCache(redis_client, ttl_seconds=60)
    assert await cache.get("") is None
    await cache.set("", "TOK")
    await cache.set("https://example.com/", "")
    assert await cache.get("https://example.com/") is None


@pytest.mark.asyncio
async def test_key_uses_sha1_not_raw_url(redis_client):
    cache = ImageCache(redis_client, ttl_seconds=60)
    long_url = "https://example.com/" + "a" * 5000
    await cache.set(long_url, "TOK")
    keys = await redis_client.keys("max:image_token:*")
    assert len(keys) == 1
    # SHA1 hex digest is 40 chars; the key must NOT contain the original URL.
    key = keys[0]
    assert len(key) == len("max:image_token:") + 40
    assert "aaaa" not in key
