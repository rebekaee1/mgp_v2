"""add uon_api_key and uon_source to assistants

Revision ID: i9j0k1l2m3n
Revises: h8i9j0k1l2m
Create Date: 2026-04-14
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "i9j0k1l2m3n"
down_revision: Union[str, None] = "h8i9j0k1l2m"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assistants", sa.Column("uon_api_key", sa.Text(), nullable=True))
    op.add_column("assistants", sa.Column("uon_source", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("assistants", "uon_source")
    op.drop_column("assistants", "uon_api_key")
