"""add tour_subscriptions and contact_optout (Feature 2: tour monitoring)

Revision ID: n4o5p6q7r8s
Revises: m3n4o5p6q7r
Create Date: 2026-06-03

Feature 2 — клиент подписывается на мониторинг туров; фоновый джоб ищет в
Tourvisor и шлёт тизер при появлении подходящего/подешевевшего тура.

  • tour_subscriptions — критерии + базовая цена + дедуп/каденс/жизненный цикл
  • contact_optout     — общий do-not-contact (Ф.1 + Ф.2): кого больше не трогаем

Обе таблицы тенант-агностичны; включение фичи делается на стороне промпта/handler
(только для тенантов с включённой подпиской), так что существующие тенанты не
затрагиваются.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "n4o5p6q7r8s"
down_revision: Union[str, None] = "m3n4o5p6q7r"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "tour_subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("assistants.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True),
                  sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False, server_default="max"),
        sa.Column("external_user_id", sa.String(64), nullable=True),
        sa.Column("external_chat_id", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="active"),
        # criteria
        sa.Column("departure", sa.Integer(), nullable=True),
        sa.Column("country", sa.Integer(), nullable=True),
        sa.Column("regions", sa.String(255), nullable=True),
        sa.Column("dest_text", sa.String(128), nullable=True),
        sa.Column("date_from", sa.String(10), nullable=True),
        sa.Column("date_to", sa.String(10), nullable=True),
        sa.Column("nights_from", sa.Integer(), nullable=True),
        sa.Column("nights_to", sa.Integer(), nullable=True),
        sa.Column("adults", sa.Integer(), nullable=True),
        sa.Column("children", sa.Integer(), nullable=True),
        sa.Column("child_ages", postgresql.JSONB(), nullable=True),
        sa.Column("min_stars", sa.Integer(), nullable=True),
        sa.Column("budget", sa.Integer(), nullable=True),
        sa.Column("hotel_codes", postgresql.JSONB(), nullable=True),
        sa.Column("hotel_name", sa.String(255), nullable=True),
        # baseline & dedup
        sa.Column("baseline_price", sa.Integer(), nullable=True),
        sa.Column("seen_codes", postgresql.JSONB(), nullable=True),
        sa.Column("last_notified_price", sa.Integer(), nullable=True),
        sa.Column("last_notified_hotelcode", sa.String(32), nullable=True),
        sa.Column("last_tourid", sa.String(64), nullable=True),
        sa.Column("last_notified_at", sa.DateTime(timezone=True), nullable=True),
        # cadence & lifecycle
        sa.Column("notifications_sent", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("silent_streak", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_reply_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("travel_date", sa.String(10), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("stop_reason", sa.String(32), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_tour_subs_status_assistant", "tour_subscriptions",
                    ["status", "assistant_id"])
    op.create_index("ix_tour_subs_user", "tour_subscriptions",
                    ["assistant_id", "external_user_id"])
    op.create_index("ix_tour_subs_expires", "tour_subscriptions",
                    ["status", "expires_at"])

    op.create_table(
        "contact_optout",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("assistant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("external_user_id", sa.String(64), nullable=True),
        sa.Column("channel", sa.String(16), nullable=False, server_default="max"),
        sa.Column("reason", sa.String(32), nullable=True),
        sa.Column("source", sa.String(32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("uq_contact_optout_user", "contact_optout",
                    ["assistant_id", "external_user_id", "channel"], unique=True)


def downgrade() -> None:
    op.drop_index("uq_contact_optout_user", table_name="contact_optout")
    op.drop_table("contact_optout")
    op.drop_index("ix_tour_subs_expires", table_name="tour_subscriptions")
    op.drop_index("ix_tour_subs_user", table_name="tour_subscriptions")
    op.drop_index("ix_tour_subs_status_assistant", table_name="tour_subscriptions")
    op.drop_table("tour_subscriptions")
