"""add sync config to assistants and remote_id to messages/tour_searches

Revision ID: d4e5f6g7h8i9
Revises: c3d4e5f6g7h8
Create Date: 2026-03-05
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "d4e5f6g7h8i9"
down_revision: Union[str, None] = "c3d4e5f6g7h8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Sync config columns on assistants ──
    op.add_column("assistants", sa.Column("sync_enabled", sa.Boolean(), server_default="false", nullable=False))
    op.add_column("assistants", sa.Column("sync_ssh_host", sa.String(255), nullable=True))
    op.add_column("assistants", sa.Column("sync_ssh_port", sa.Integer(), server_default="22", nullable=False))
    op.add_column("assistants", sa.Column("sync_ssh_user", sa.String(128), server_default="root", nullable=False))
    op.add_column("assistants", sa.Column("sync_ssh_password", sa.Text(), nullable=True))
    op.add_column("assistants", sa.Column("sync_pg_port", sa.Integer(), server_default="5432", nullable=False))
    op.add_column("assistants", sa.Column("sync_pg_user", sa.String(128), nullable=True))
    op.add_column("assistants", sa.Column("sync_pg_password", sa.Text(), nullable=True))
    op.add_column("assistants", sa.Column("sync_pg_db", sa.String(128), nullable=True))
    op.add_column("assistants", sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assistants", sa.Column("last_sync_status", sa.String(16), nullable=True))
    op.add_column("assistants", sa.Column("last_sync_error", sa.Text(), nullable=True))

    # ── 2. remote_id on messages ──
    op.add_column("messages", sa.Column("remote_id", sa.Integer(), nullable=True))
    op.execute("UPDATE messages SET remote_id = id WHERE remote_id IS NULL")
    op.create_index("uq_messages_conv_remote", "messages", ["conversation_id", "remote_id"], unique=True)

    # ── 3. remote_id on tour_searches ──
    op.add_column("tour_searches", sa.Column("remote_id", sa.Integer(), nullable=True))
    op.execute("UPDATE tour_searches SET remote_id = id WHERE remote_id IS NULL")
    op.create_index("uq_tour_searches_conv_remote", "tour_searches", ["conversation_id", "remote_id"], unique=True)

    # ── 4. Migrate MGP sync credentials from ENV to first assistant ──
    import os
    ssh_host = os.environ.get("MGP_SSH_HOST", "")
    if ssh_host:
        ssh_port = os.environ.get("MGP_SSH_PORT", "22")
        ssh_user = os.environ.get("MGP_SSH_USER", "root")
        ssh_pass = os.environ.get("MGP_SSH_PASSWORD", "")
        pg_port = os.environ.get("MGP_PG_PORT", "5432")
        pg_user = os.environ.get("MGP_PG_USER", "mgp")
        pg_pass = os.environ.get("MGP_PG_PASSWORD", "mgp")
        pg_db = os.environ.get("MGP_PG_DB", "mgp")
        op.execute(
            sa.text(
                "UPDATE assistants SET "
                "sync_enabled = true, "
                "sync_ssh_host = :ssh_host, "
                "sync_ssh_port = :ssh_port, "
                "sync_ssh_user = :ssh_user, "
                "sync_ssh_password = :ssh_pass, "
                "sync_pg_port = :pg_port, "
                "sync_pg_user = :pg_user, "
                "sync_pg_password = :pg_pass, "
                "sync_pg_db = :pg_db "
                "WHERE id = (SELECT id FROM assistants ORDER BY created_at LIMIT 1)"
            ).bindparams(
                ssh_host=ssh_host, ssh_port=int(ssh_port), ssh_user=ssh_user,
                ssh_pass=ssh_pass or None, pg_port=int(pg_port),
                pg_user=pg_user, pg_pass=pg_pass, pg_db=pg_db,
            )
        )


def downgrade() -> None:
    op.drop_index("uq_tour_searches_conv_remote", table_name="tour_searches")
    op.drop_column("tour_searches", "remote_id")

    op.drop_index("uq_messages_conv_remote", table_name="messages")
    op.drop_column("messages", "remote_id")

    op.drop_column("assistants", "last_sync_error")
    op.drop_column("assistants", "last_sync_status")
    op.drop_column("assistants", "last_sync_at")
    op.drop_column("assistants", "sync_pg_db")
    op.drop_column("assistants", "sync_pg_password")
    op.drop_column("assistants", "sync_pg_user")
    op.drop_column("assistants", "sync_pg_port")
    op.drop_column("assistants", "sync_ssh_password")
    op.drop_column("assistants", "sync_ssh_user")
    op.drop_column("assistants", "sync_ssh_port")
    op.drop_column("assistants", "sync_ssh_host")
    op.drop_column("assistants", "sync_enabled")
