"""add crm_provider and МоиДокументы-Туризм credentials to assistants

Revision ID: m3n4o5p6q7r
Revises: l2m3n4o5p6q
Create Date: 2026-05-29

Adds per-tenant support for the «МоиДокументы-Туризм» CRM (moidokumenti.ru)
alongside the existing U-ON integration:
  - crm_provider      — "uon" (default) | "moidoc"
  - moidoc_account_url — cabinet URL, e.g. https://trevel-time.moidokumenti.ru
  - moidoc_api_key     — API access key
  - moidoc_source      — lead source label

All columns are nullable so existing U-ON tenants are unaffected
(crm_provider NULL is treated as "uon" at runtime).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "m3n4o5p6q7r"
down_revision: Union[str, None] = "l2m3n4o5p6q"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assistants", sa.Column("crm_provider", sa.String(32), nullable=True))
    op.add_column("assistants", sa.Column("moidoc_account_url", sa.Text(), nullable=True))
    op.add_column("assistants", sa.Column("moidoc_api_key", sa.Text(), nullable=True))
    op.add_column("assistants", sa.Column("moidoc_source", sa.String(128), nullable=True))


def downgrade() -> None:
    op.drop_column("assistants", "moidoc_source")
    op.drop_column("assistants", "moidoc_api_key")
    op.drop_column("assistants", "moidoc_account_url")
    op.drop_column("assistants", "crm_provider")
