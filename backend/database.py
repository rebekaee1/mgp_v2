"""
SQLAlchemy 2.0 sync engine + session factory.
Graceful degradation: если PostgreSQL недоступен, приложение работает без БД.
"""

import logging
import re as _re
from contextlib import contextmanager
from typing import Optional, Generator

from sqlalchemy import create_engine, event, text

_DASH_RE = _re.compile(
    r'[\u002D\u2010\u2011\u2012\u2013\u2014\u2015\u2212\u00AD\uFE63\uFF0D]'
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("mgp_bot")

_engine = None
_SessionLocal = None
_db_available = False


class Base(DeclarativeBase):
    pass


def _ensure_psycopg_url(url: str) -> str:
    """Auto-fix postgresql:// → postgresql+psycopg:// for psycopg3 compatibility."""
    if url.startswith("postgresql://") and "+" not in url.split("://")[0]:
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def init_db(database_url: str) -> bool:
    """
    Инициализировать подключение к БД (PostgreSQL или SQLite).
    Возвращает True если подключение успешно.
    """
    global _engine, _SessionLocal, _db_available

    is_sqlite = database_url.startswith("sqlite")

    if not is_sqlite:
        database_url = _ensure_psycopg_url(database_url)

    try:
        kwargs = {} if is_sqlite else dict(
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        _engine = create_engine(database_url, echo=False, **kwargs)

        if is_sqlite:
            def _normalize(s):
                if not s:
                    return None
                s = s.lower().replace("ё", "е")
                s = _DASH_RE.sub(" ", s)
                return s

            @event.listens_for(_engine, "connect")
            def _register_unicode_funcs(dbapi_conn, connection_record):
                dbapi_conn.create_function("py_lower", 1, _normalize)

        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))

        if is_sqlite:
            Base.metadata.create_all(_engine)
            logger.info("SQLite database ready: %s", database_url)
        else:
            logger.info("PostgreSQL connected: %s", database_url.split("@")[-1])

        _SessionLocal = sessionmaker(bind=_engine, expire_on_commit=False)
        _db_available = True
        return True

    except Exception as e:
        _db_available = False
        logger.warning("Database unavailable (%s) — running without DB", e)
        return False


def is_db_available() -> bool:
    return _db_available


@contextmanager
def get_db() -> Generator[Optional[Session], None, None]:
    """
    Context manager для DB сессии.
    Yields None если БД недоступна (graceful degradation).
    """
    if not _db_available or _SessionLocal is None:
        yield None
        return

    session: Session = _SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_health() -> bool:
    """Health check для /api/health."""
    if not _db_available or _engine is None:
        return False
    try:
        with _engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
