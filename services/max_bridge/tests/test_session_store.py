import pytest
from fakeredis import aioredis as fake_aioredis

from app.session_store import SessionStore


@pytest.fixture
def store():
    redis = fake_aioredis.FakeRedis(decode_responses=True)
    return SessionStore(redis, ttl_seconds=60)


@pytest.mark.asyncio
async def test_first_call_creates_session(store):
    session_id, created = await store.get_or_create_session(42)
    assert created is True
    assert session_id.startswith("max-42-")


@pytest.mark.asyncio
async def test_second_call_returns_same_session(store):
    first_id, first_created = await store.get_or_create_session(42)
    second_id, second_created = await store.get_or_create_session(42)
    assert first_created is True
    assert second_created is False
    assert first_id == second_id


@pytest.mark.asyncio
async def test_different_users_get_different_sessions(store):
    a_id, _ = await store.get_or_create_session(1)
    b_id, _ = await store.get_or_create_session(2)
    assert a_id != b_id


@pytest.mark.asyncio
async def test_reset_session_creates_new_one(store):
    first_id, _ = await store.get_or_create_session(42)
    await store.reset_session(42)
    second_id, created = await store.get_or_create_session(42)
    assert created is True
    assert first_id != second_id
