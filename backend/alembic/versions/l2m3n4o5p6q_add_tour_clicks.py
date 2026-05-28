"""add tour_clicks to conversations

Revision ID: l2m3n4o5p6q
Revises: k1l2m3n4o5p
Create Date: 2026-05-29

Adds a per-conversation counter of "Забронировать" clicks tracked via the
signed /go redirect. >0 marks a real transition to a tour page on the partner
site, powering the LK "Перешли на тур" funnel stage (distinct from the
text-derived has_booking_intent). server_default="0" backfills existing rows.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "l2m3n4o5p6q"
down_revision: Union[str, None] = "k1l2m3n4o5p"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column(
            "tour_clicks",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("conversations", "tour_clicks")
