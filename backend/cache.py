"""
Redis cache wrapper с graceful degradation.
Если Redis недоступен — все операции возвращают None/True (пропускают),
приложение продолжает работать без кеша.
"""

import json
import logging
from typing import Optional, Any

import redis as redis_lib

logger = logging.getLogger("mgp_bot")

_client: Optional[redis_lib.Redis] = None
_available = False


def init_cache(redis_url: str) -> bool:
    """Инициализировать Redis. Возвращает True если подключение успешно."""
    global _client, _available
    try:
        _client = redis_lib.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=3,
            socket_timeout=2,
        )
        _client.ping()
        _available = True
        logger.info("Redis connected: %s", redis_url.split("@")[-1])
        return True
    except Exception as e:
        _available = False
        logger.warning("Redis unavailable (%s) — running without cache", e)
        return False


def is_cache_available() -> bool:
    return _available


def check_health() -> bool:
    if not _available or _client is None:
        return False
    try:
        return _client.ping()
    except Exception:
        return False


# --- JSON cache (TourVisor dictionaries, hotel info) ---

def cache_get(key: str) -> Optional[Any]:
    """Получить значение из кеша. None если нет или Redis недоступен."""
    if not _available or _client is None:
        return None
    try:
        raw = _client.get(key)
        if raw is None:
            return None
        return json.loads(raw)
    except Exception:
        return None


def cache_set(key: str, value: Any, ttl_seconds: int = 86400) -> bool:
    """Записать в кеш с TTL. False при ошибке."""
    if not _available or _client is None:
        return False
    try:
        _client.setex(key, ttl_seconds, json.dumps(value, ensure_ascii=False, default=str))
        return True
    except Exception:
        return False


# --- Rate limiting ---

def rate_limit_check(key: str, limit: int, window_seconds: int = 60) -> bool:
    """
    Проверить rate limit. Возвращает True если запрос разрешён.
    При ошибке Redis — всегда разрешает (graceful degradation).
    """
    if not _available or _client is None:
        return True
    try:
        pipe = _client.pipeline()
        pipe.incr(key)
        pipe.expire(key, window_seconds)
        results = pipe.execute()
        current = results[0]
        return current <= limit
    except Exception:
        return True


# --- Metrics counters ---

def metric_incr(key: str, ttl_seconds: int = 172800) -> None:
    """Инкрементировать счётчик метрики (fire-and-forget)."""
    if not _available or _client is None:
        return
    try:
        pipe = _client.pipeline()
        pipe.incr(key)
        pipe.expire(key, ttl_seconds)
        pipe.execute()
    except Exception:
        pass


def metric_get(key: str) -> int:
    """Получить значение счётчика."""
    if not _available or _client is None:
        return 0
    try:
        val = _client.get(key)
        return int(val) if val else 0
    except Exception:
        return 0
