"""add provisioning callback tracking

Revision ID: f6g7h8i9j0k
Revises: e5f6g7h8i9j0
Create Date: 2026-03-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "f6g7h8i9j0k"
down_revision: Union[str, None] = "e5f6g7h8i9j0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("provisioning_requests", sa.Column("callback_delivery_status", sa.String(length=32), nullable=True))
    op.add_column("provisioning_requests", sa.Column("callback_attempts", sa.Integer(), server_default="0", nullable=False))
    op.add_column("provisioning_requests", sa.Column("callback_last_status_code", sa.Integer(), nullable=True))
    op.add_column("provisioning_requests", sa.Column("callback_last_error", sa.Text(), nullable=True))
    op.add_column("provisioning_requests", sa.Column("callback_last_attempt_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("provisioning_requests", "callback_last_attempt_at")
    op.drop_column("provisioning_requests", "callback_last_error")
    op.drop_column("provisioning_requests", "callback_last_status_code")
    op.drop_column("provisioning_requests", "callback_attempts")
    op.drop_column("provisioning_requests", "callback_delivery_status")
