"""
ORM-модели для PostgreSQL — полное логирование диалогов, поисков и API-вызовов.
Данные структурированы для будущего личного кабинета и аналитики.
Совместимость: Optional[] для Python 3.9+.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    BigInteger, DateTime, Index, Integer, String, Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Conversation(Base):
    """
    Сессия чата. 1 conversation = 1 conversation_id от фронтенда.
    Хранит мета-данные для аналитики и будущего личного кабинета.
    """
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    llm_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    tour_cards_shown: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default="active")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )
    tour_searches: Mapped[List["TourSearch"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_conversations_started", "started_at"),
        Index("ix_conversations_status", "status"),
    )


class Message(Base):
    """
    Каждое сообщение в диалоге: user, assistant, tool.
    Хранит полный путь: что спросил пользователь, что ответила LLM,
    какие tool_calls были сделаны, какие карточки туров показаны.
    """
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    tour_cards: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    tokens_prompt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_completion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
    )


class TourSearch(Base):
    """
    Лог поисков туров. Каждый search_tours/get_hot_tours вызов.
    Для аналитики: популярные направления, средний бюджет, конверсия.
    """
    __tablename__ = "tour_searches"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    requestid: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    search_type: Mapped[str] = mapped_column(String(16), default="regular")
    departure: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    country: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    regions: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    date_from: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    date_to: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    nights_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    nights_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    adults: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    children: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    stars: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    meal: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_from: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    price_to: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    hotels_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tours_found: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    min_price: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="tour_searches")

    __table_args__ = (
        Index("ix_tour_searches_country", "country", "created_at"),
    )


class ApiCall(Base):
    """
    Лог ВСЕХ внешних API вызовов: TourVisor, Yandex, OpenAI.
    Для мониторинга лимитов, диагностики ошибок, расчёта стоимости.
    """
    __tablename__ = "api_calls"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    service: Mapped[str] = mapped_column(String(16), nullable=False)
    endpoint: Mapped[str] = mapped_column(String(128), nullable=False)
    response_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    response_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_used: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        Index("ix_api_calls_service", "service", "created_at"),
    )


class DailyStat(Base):
    """Агрегированная дневная статистика для быстрого дашборда."""
    __tablename__ = "daily_stats"

    date: Mapped[str] = mapped_column(String(10), primary_key=True)
    conversations_total: Mapped[int] = mapped_column(Integer, default=0)
    messages_total: Mapped[int] = mapped_column(Integer, default=0)
    searches_total: Mapped[int] = mapped_column(Integer, default=0)
    tours_shown: Mapped[int] = mapped_column(Integer, default=0)
    avg_response_ms: Mapped[int] = mapped_column(Integer, default=0)
    errors_count: Mapped[int] = mapped_column(Integer, default=0)
    tokens_total: Mapped[int] = mapped_column(Integer, default=0)
    unique_ips: Mapped[int] = mapped_column(Integer, default=0)
