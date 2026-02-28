"""
SQLAlchemy 2.0 sync engine + session factory.
Graceful degradation: если PostgreSQL недоступен, приложение работает без БД.
"""

import logging
from contextlib import contextmanager
from typing import Optional, Generator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

logger = logging.getLogger("mgp_bot")

_engine = None
_SessionLocal = None
_db_available = False


class Base(DeclarativeBase):
    pass


def init_db(database_url: str) -> bool:
    """
    Инициализировать подключение к БД (PostgreSQL или SQLite).
    Возвращает True если подключение успешно.
    """
    global _engine, _SessionLocal, _db_available

    is_sqlite = database_url.startswith("sqlite")

    try:
        kwargs = {} if is_sqlite else dict(
            pool_size=5,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=300,
        )
        _engine = create_engine(database_url, echo=False, **kwargs)

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
