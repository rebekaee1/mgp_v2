"""add bot_server_url and allowed_domains to assistants

Revision ID: c3d4e5f6g7h8
Revises: b2c3d4e5f6g7
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6g7h8'
down_revision: Union[str, None] = 'b2c3d4e5f6g7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('assistants', sa.Column('bot_server_url', sa.Text(), nullable=True))
    op.add_column('assistants', sa.Column('allowed_domains', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('assistants', 'allowed_domains')
    op.drop_column('assistants', 'bot_server_url')
