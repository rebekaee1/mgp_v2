"""add reconciliation requests

Revision ID: h8i9j0k1l2m
Revises: g7h8i9j0k1l
Create Date: 2026-03-16
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "h8i9j0k1l2m"
down_revision: Union[str, None] = "g7h8i9j0k1l"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "reconciliation_requests",
        sa.Column("reconciliation_request_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("control_plane_request_id", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("assistant_id", sa.Uuid(), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), nullable=True),
        sa.Column("occurred_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("occurred_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("limit", sa.Integer(), server_default="500", nullable=False),
        sa.Column("deliver_now", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latest_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("queued_events", sa.Integer(), server_default="0", nullable=False),
        sa.Column("matched_conversations", sa.Integer(), server_default="0", nullable=False),
        sa.Column("delivered_events", sa.Integer(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("reconciliation_request_id"),
    )
    op.create_index(
        "ix_reconciliation_requests_status",
        "reconciliation_requests",
        ["status", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_reconciliation_requests_idempotency",
        "reconciliation_requests",
        ["idempotency_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_reconciliation_requests_idempotency", table_name="reconciliation_requests")
    op.drop_index("ix_reconciliation_requests_status", table_name="reconciliation_requests")
    op.drop_table("reconciliation_requests")
