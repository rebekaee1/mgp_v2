"""add runtime metadata and provisioning requests

Revision ID: e5f6g7h8i9j0
Revises: d4e5f6g7h8i9
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = "e5f6g7h8i9j0"
down_revision: Union[str, None] = "d4e5f6g7h8i9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assistants", sa.Column("runtime_metadata", postgresql.JSONB(astext_type=sa.Text()), nullable=True))

    op.create_table(
        "provisioning_requests",
        sa.Column("provisioning_request_id", sa.String(length=64), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("control_plane_request_id", sa.String(length=128), nullable=True),
        sa.Column("callback_url", sa.Text(), nullable=True),
        sa.Column("callback_token", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("company_id", sa.Uuid(), nullable=True),
        sa.Column("assistant_id", sa.Uuid(), nullable=True),
        sa.Column("request_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("latest_result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_retryable", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("provisioning_request_id"),
    )
    op.create_index("ix_provisioning_requests_status", "provisioning_requests", ["status", "created_at"], unique=False)
    op.create_index("ix_provisioning_requests_idempotency", "provisioning_requests", ["idempotency_key"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_provisioning_requests_idempotency", table_name="provisioning_requests")
    op.drop_index("ix_provisioning_requests_status", table_name="provisioning_requests")
    op.drop_table("provisioning_requests")
    op.drop_column("assistants", "runtime_metadata")
