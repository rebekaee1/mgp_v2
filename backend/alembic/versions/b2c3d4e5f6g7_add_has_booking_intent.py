"""add has_booking_intent to conversations

Revision ID: b2c3d4e5f6g7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-02
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'b2c3d4e5f6g7'
down_revision: Union[str, None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('conversations',
                  sa.Column('has_booking_intent', sa.Boolean(),
                            nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('conversations', 'has_booking_intent')
