"""add multitenancy: companies, assistants, users + conversations.assistant_id

Revision ID: a1b2c3d4e5f6
Revises: 0d624d07830c
Create Date: 2026-02-26
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, None] = '0d624d07830c'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'companies',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('slug', sa.String(64), unique=True, nullable=False),
        sa.Column('logo_url', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table(
        'assistants',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('tourvisor_login', sa.String(128), nullable=True),
        sa.Column('tourvisor_pass', sa.String(128), nullable=True),
        sa.Column('llm_provider', sa.String(16), server_default='openai'),
        sa.Column('llm_api_key', sa.Text(), nullable=True),
        sa.Column('llm_model', sa.String(64), nullable=True),
        sa.Column('system_prompt', sa.Text(), nullable=True),
        sa.Column('faq_content', sa.Text(), nullable=True),
        sa.Column('widget_config', postgresql.JSONB(), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.create_table(
        'users',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('company_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('companies.id', ondelete='CASCADE'), nullable=False),
        sa.Column('email', sa.String(255), unique=True, nullable=False),
        sa.Column('password_hash', sa.String(255), nullable=False),
        sa.Column('name', sa.String(128), nullable=False),
        sa.Column('role', sa.String(16), server_default='admin'),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )

    op.add_column('conversations',
                  sa.Column('assistant_id', postgresql.UUID(as_uuid=True),
                            sa.ForeignKey('assistants.id', ondelete='SET NULL'),
                            nullable=True))
    op.create_index('ix_conversations_assistant', 'conversations',
                    ['assistant_id', 'started_at'])


def downgrade() -> None:
    op.drop_index('ix_conversations_assistant', table_name='conversations')
    op.drop_column('conversations', 'assistant_id')
    op.drop_table('users')
    op.drop_table('assistants')
    op.drop_table('companies')
