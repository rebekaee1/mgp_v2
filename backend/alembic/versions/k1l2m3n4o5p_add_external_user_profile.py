"""add external_user profile fields (first/last/display name + chat_id)

Revision ID: k1l2m3n4o5p
Revises: j0k1l2m3n4o
Create Date: 2026-05-13

The MAX webhook payload already carries the sender's profile (first_name,
last_name, display name) and the bot↔user chat_id on every message. We
persist these on the ``conversations`` row so the LK side can render a
"client card" next to each dialog (name, MAX ID, link to MAX profile)
*without* an extra round-trip to the bridge. ``external_chat_id`` is
kept around so we can later let managers reply to the user from the LK
UI via a single bot ``POST /messages`` call.

All four columns are nullable — they only apply to channels that expose
this metadata (currently ``max``). The web widget leaves them ``NULL``.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "k1l2m3n4o5p"
down_revision: Union[str, None] = "j0k1l2m3n4o"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("external_first_name", sa.String(64), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("external_last_name", sa.String(64), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("external_user_name", sa.String(128), nullable=True),
    )
    op.add_column(
        "conversations",
        sa.Column("external_chat_id", sa.String(64), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "external_chat_id")
    op.drop_column("conversations", "external_user_name")
    op.drop_column("conversations", "external_last_name")
    op.drop_column("conversations", "external_first_name")
