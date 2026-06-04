"""add conversations.warm_nudge_sent_at (warm-nudge: one nudge per dialogue)

Revision ID: o5p6q7r8s9t
Revises: n4o5p6q7r8s
Create Date: 2026-06-04

«Тёплый добив» — фоновый джоб пишет клиенту через ~15 минут молчания после
показанной подборки (мягкий переспрос + оффер мониторинга). Столбец фиксирует
момент отправки, чтобы добить клиента не более одного раза за диалог.

Аддитивно и тенант-агностично: nullable-столбец, существующие строки = NULL,
включение фичи делается на стороне джоба (whitelist ассистентов).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "o5p6q7r8s9t"
down_revision: Union[str, None] = "n4o5p6q7r8s"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("warm_nudge_sent_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "warm_nudge_sent_at")
