"""add conversations operator-handoff columns (manager-in-chat, MAX)

Revision ID: p6q7r8s9t0u
Revises: o5p6q7r8s9t
Create Date: 2026-06-09

Фича «вход менеджера в чат» (handoff). Все столбцы аддитивные:
  • operator_mode            — ИИ на паузе (true ⇒ LLM не отвечает);
  • operator_mode_since      — когда включился operator_mode;
  • operator_last_activity_at— последняя активность оператора (для авто-возврата);
  • handoff_state            — none|requested|operator|returned;
  • handoff_reason           — book_click|booking_intent|phrase|contact|manual;
  • operator_actor           — кто за рулём (для баннера в ЛК).

Безопасно/обратимо: NOT NULL поля с server_default (все существующие строки →
operator_mode=false, handoff_state='none'); фича включается флагом (per-tenant
allow-list + channel='max'), миграция сама ничего не активирует. Частичный индекс
ускоряет фоновый монитор авто-возврата (скан только активных operator-диалогов).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p6q7r8s9t0u"
down_revision: Union[str, None] = "o5p6q7r8s9t"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "operator_mode",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("operator_mode_since", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "operator_last_activity_at", sa.DateTime(timezone=True), nullable=True
        ),
    )
    op.add_column(
        "conversations",
        sa.Column(
            "handoff_state",
            sa.String(length=16),
            nullable=False,
            server_default="none",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("handoff_reason", sa.String(length=24), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("operator_actor", sa.String(length=64), nullable=True),
    )
    # Частичный индекс: монитор авто-возврата сканирует только активные диалоги.
    op.create_index(
        "ix_conversations_operator_active",
        "conversations",
        ["operator_mode_since"],
        unique=False,
        postgresql_where=sa.text("operator_mode"),
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_operator_active", table_name="conversations")
    op.drop_column("conversations", "operator_actor")
    op.drop_column("conversations", "handoff_reason")
    op.drop_column("conversations", "handoff_state")
    op.drop_column("conversations", "operator_last_activity_at")
    op.drop_column("conversations", "operator_mode_since")
    op.drop_column("conversations", "operator_mode")
