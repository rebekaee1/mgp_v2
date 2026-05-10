"""structlog wiring + correlation-id helper.

We keep this module deliberately small: production logs go to stdout in JSON
so the existing docker logging driver picks them up unchanged.
"""

from __future__ import annotations

import logging
import sys
import uuid
from contextvars import ContextVar
from typing import Optional

import structlog

_correlation_id: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)


def _add_correlation_id(_, __, event_dict: dict) -> dict:
    cid = _correlation_id.get()
    if cid:
        event_dict.setdefault("correlation_id", cid)
    return event_dict


def configure_logging(level: str = "INFO") -> None:
    """Wire stdlib logging + structlog to emit JSON to stdout.

    Called once on app startup. Safe to call multiple times — calls are
    idempotent thanks to structlog.configure replacing previous setup.
    """
    log_level = getattr(logging, level.upper(), logging.INFO)
    logging.basicConfig(
        level=log_level,
        format="%(message)s",
        stream=sys.stdout,
        force=True,
    )

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            _add_correlation_id,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )


def new_correlation_id() -> str:
    """Generate a fresh correlation-id and bind it to the current context."""
    cid = uuid.uuid4().hex[:16]
    _correlation_id.set(cid)
    return cid


def set_correlation_id(cid: str) -> None:
    _correlation_id.set(cid)


def get_correlation_id() -> Optional[str]:
    return _correlation_id.get()


def get_logger(name: str = "max_bridge"):
    return structlog.get_logger(name)
