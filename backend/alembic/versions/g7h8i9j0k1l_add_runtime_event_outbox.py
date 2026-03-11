"""add runtime event outbox

Revision ID: g7h8i9j0k1l
Revises: f6g7h8i9j0k
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "g7h8i9j0k1l"
down_revision: Union[str, None] = "f6g7h8i9j0k"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "runtime_event_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=False),
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status_code", sa.Integer(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("locked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["assistant_id"], ["assistants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["conversation_id"], ["conversations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_runtime_event_outbox_assistant_event",
        "runtime_event_outbox",
        ["assistant_id", "event_id"],
        unique=True,
    )
    op.create_index(
        "ix_runtime_event_outbox_status_retry",
        "runtime_event_outbox",
        ["status", "next_retry_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_runtime_event_outbox_conversation",
        "runtime_event_outbox",
        ["conversation_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_runtime_event_outbox_conversation", table_name="runtime_event_outbox")
    op.drop_index("ix_runtime_event_outbox_status_retry", table_name="runtime_event_outbox")
    op.drop_index("uq_runtime_event_outbox_assistant_event", table_name="runtime_event_outbox")
    op.drop_table("runtime_event_outbox")
