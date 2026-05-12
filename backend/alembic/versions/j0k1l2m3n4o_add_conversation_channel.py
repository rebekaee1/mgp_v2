"""add channel + external_user_id to conversations

Revision ID: j0k1l2m3n4o
Revises: i9j0k1l2m3n
Create Date: 2026-05-12

Adds per-conversation channel attribution so the LK side can render different
badges for widget vs MAX bot dialogs (without re-deriving from session_id
prefixes). ``external_user_id`` is the user identifier inside the source
channel (e.g. MAX user_id). Both columns are populated by the runtime on the
first INSERT and never overwritten on subsequent updates within the same
conversation.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "j0k1l2m3n4o"
down_revision: Union[str, None] = "i9j0k1l2m3n"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "channel",
            sa.String(16),
            nullable=False,
            server_default="widget",
        ),
    )
    op.add_column(
        "conversations",
        sa.Column("external_user_id", sa.String(64), nullable=True),
    )
    op.create_index(
        "ix_conversations_channel_started",
        "conversations",
        ["channel", "started_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_conversations_channel_started", table_name="conversations")
    op.drop_column("conversations", "external_user_id")
    op.drop_column("conversations", "channel")
