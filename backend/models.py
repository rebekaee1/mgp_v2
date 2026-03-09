"""
ORM-модели для PostgreSQL — полное логирование диалогов, поисков и API-вызовов.
Данные структурированы для личного кабинета и аналитики.
Совместимость: Optional[] для Python 3.9+.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional, List

from sqlalchemy import (
    BigInteger, Boolean, DateTime, Index, Integer, JSON, String, Text,
    ForeignKey, Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

UUID = Uuid

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ── Multi-tenancy models ─────────────────────────────────────────────────────

class Company(Base):
    """Компания-клиент, использующая AI-ассистента."""
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    users: Mapped[List["User"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )
    assistants: Mapped[List["Assistant"]] = relationship(
        back_populates="company", cascade="all, delete-orphan"
    )


class Assistant(Base):
    """AI-ассистент, привязанный к компании. Хранит ключи API и конфиг виджета."""
    __tablename__ = "assistants"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    tourvisor_login: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    tourvisor_pass: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    llm_provider: Mapped[str] = mapped_column(String(16), default="openai")
    llm_api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    llm_model: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    faq_content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    widget_config: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    runtime_metadata: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    bot_server_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    allowed_domains: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    # ── Sync configuration (per-assistant remote DB credentials) ──
    sync_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    sync_ssh_host: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    sync_ssh_port: Mapped[int] = mapped_column(Integer, default=22)
    sync_ssh_user: Mapped[str] = mapped_column(String(128), default="root")
    sync_ssh_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sync_pg_port: Mapped[int] = mapped_column(Integer, default=5432)
    sync_pg_user: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    sync_pg_password: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sync_pg_db: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)

    # ── Sync status (written by sync engine, read by dashboard) ──
    last_sync_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_sync_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    last_sync_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    company: Mapped["Company"] = relationship(back_populates="assistants")
    conversations: Mapped[List["Conversation"]] = relationship(
        back_populates="assistant"
    )


class User(Base):
    """Пользователь ЛК (менеджер / администратор компании)."""
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    role: Mapped[str] = mapped_column(String(16), default="admin")
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    company: Mapped["Company"] = relationship(back_populates="users")


# ── Chat / Analytics models ──────────────────────────────────────────────────

class Conversation(Base):
    """
    Сессия чата. 1 conversation = 1 conversation_id от фронтенда.
    Хранит мета-данные для аналитики и личного кабинета.
    """
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(), primary_key=True, default=uuid.uuid4
    )
    session_id: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    assistant_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(),
        ForeignKey("assistants.id", ondelete="SET NULL"),
        nullable=True,
    )
    llm_provider: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)
    ip_address: Mapped[Optional[str]] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    search_count: Mapped[int] = mapped_column(Integer, default=0)
    tour_cards_shown: Mapped[int] = mapped_column(Integer, default=0)
    has_booking_intent: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="0"
    )
    status: Mapped[str] = mapped_column(String(16), default="active")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    last_active_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    assistant: Mapped[Optional["Assistant"]] = relationship(
        back_populates="conversations"
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
        Index("ix_conversations_assistant", "assistant_id", "started_at"),
    )


class Message(Base):
    """
    Каждое сообщение в диалоге: user, assistant, tool.
    Хранит полный путь: что спросил пользователь, что ответила LLM,
    какие tool_calls были сделаны, какие карточки туров показаны.
    """
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    remote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    tool_call_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tool_calls: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    tour_cards: Mapped[Optional[list]] = mapped_column(JSON, nullable=True)
    tokens_prompt: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    tokens_completion: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")

    __table_args__ = (
        Index("ix_messages_conv_created", "conversation_id", "created_at"),
        Index("uq_messages_conv_remote", "conversation_id", "remote_id", unique=True),
    )


class TourSearch(Base):
    """
    Лог поисков туров. Каждый search_tours/get_hot_tours вызов.
    Для аналитики: популярные направления, средний бюджет, конверсия.
    """
    __tablename__ = "tour_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(),
        ForeignKey("conversations.id", ondelete="CASCADE"),
        nullable=False,
    )
    remote_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
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
        Index("uq_tour_searches_conv_remote", "conversation_id", "remote_id", unique=True),
    )


class ApiCall(Base):
    """
    Лог ВСЕХ внешних API вызовов: TourVisor, Yandex, OpenAI.
    Для мониторинга лимитов, диагностики ошибок, расчёта стоимости.
    """
    __tablename__ = "api_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(), nullable=True
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


class AIReport(Base):
    """Сохранённый AI-отчёт (один на company + period)."""
    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    company_id: Mapped[str] = mapped_column(String(64), nullable=False)
    period: Mapped[str] = mapped_column(String(8), nullable=False)
    report_text: Mapped[str] = mapped_column(Text, nullable=False)
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )

    __table_args__ = (
        Index("ix_ai_reports_company_period", "company_id", "period", unique=True),
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


class ProvisioningRequest(Base):
    """Control-plane provisioning request state for LK -> MGP orchestration."""
    __tablename__ = "provisioning_requests"

    provisioning_request_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    control_plane_request_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    callback_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    callback_token: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="accepted")
    company_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(), nullable=True)
    assistant_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(), nullable=True)
    request_payload: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    latest_result: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    error_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    error_retryable: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    __table_args__ = (
        Index("ix_provisioning_requests_status", "status", "created_at"),
        Index("ix_provisioning_requests_idempotency", "idempotency_key"),
    )
