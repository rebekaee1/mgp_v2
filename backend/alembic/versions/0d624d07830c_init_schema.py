"""init_schema

Revision ID: 0d624d07830c
Create Date: 2026-02-25
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '0d624d07830c'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'conversations',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text('gen_random_uuid()')),
        sa.Column('session_id', sa.String(64), unique=True, nullable=False),
        sa.Column('llm_provider', sa.String(16), nullable=False),
        sa.Column('model', sa.String(64), nullable=False),
        sa.Column('ip_address', sa.String(45), nullable=True),
        sa.Column('user_agent', sa.Text(), nullable=True),
        sa.Column('message_count', sa.Integer(), server_default='0'),
        sa.Column('search_count', sa.Integer(), server_default='0'),
        sa.Column('tour_cards_shown', sa.Integer(), server_default='0'),
        sa.Column('status', sa.String(16), server_default='active'),
        sa.Column('started_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
        sa.Column('last_active_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_conversations_started', 'conversations', ['started_at'])
    op.create_index('ix_conversations_status', 'conversations', ['status'])

    op.create_table(
        'messages',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(16), nullable=False),
        sa.Column('content', sa.Text(), nullable=True),
        sa.Column('tool_call_id', sa.String(64), nullable=True),
        sa.Column('tool_calls', postgresql.JSONB(), nullable=True),
        sa.Column('tour_cards', postgresql.JSONB(), nullable=True),
        sa.Column('tokens_prompt', sa.Integer(), nullable=True),
        sa.Column('tokens_completion', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_messages_conv_created', 'messages', ['conversation_id', 'created_at'])

    op.create_table(
        'tour_searches',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True),
                  sa.ForeignKey('conversations.id', ondelete='CASCADE'), nullable=False),
        sa.Column('requestid', sa.String(64), nullable=True),
        sa.Column('search_type', sa.String(16), server_default='regular'),
        sa.Column('departure', sa.Integer(), nullable=True),
        sa.Column('country', sa.Integer(), nullable=True),
        sa.Column('regions', sa.String(255), nullable=True),
        sa.Column('date_from', sa.String(10), nullable=True),
        sa.Column('date_to', sa.String(10), nullable=True),
        sa.Column('nights_from', sa.Integer(), nullable=True),
        sa.Column('nights_to', sa.Integer(), nullable=True),
        sa.Column('adults', sa.Integer(), nullable=True),
        sa.Column('children', sa.Integer(), nullable=True),
        sa.Column('stars', sa.Integer(), nullable=True),
        sa.Column('meal', sa.Integer(), nullable=True),
        sa.Column('price_from', sa.Integer(), nullable=True),
        sa.Column('price_to', sa.Integer(), nullable=True),
        sa.Column('hotels_found', sa.Integer(), nullable=True),
        sa.Column('tours_found', sa.Integer(), nullable=True),
        sa.Column('min_price', sa.Integer(), nullable=True),
        sa.Column('duration_ms', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_tour_searches_country', 'tour_searches', ['country', 'created_at'])

    op.create_table(
        'api_calls',
        sa.Column('id', sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column('conversation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('service', sa.String(16), nullable=False),
        sa.Column('endpoint', sa.String(128), nullable=False),
        sa.Column('response_code', sa.Integer(), nullable=True),
        sa.Column('response_bytes', sa.Integer(), nullable=True),
        sa.Column('tokens_used', sa.Integer(), nullable=True),
        sa.Column('latency_ms', sa.Integer(), nullable=False),
        sa.Column('error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()')),
    )
    op.create_index('ix_api_calls_service', 'api_calls', ['service', 'created_at'])

    op.create_table(
        'daily_stats',
        sa.Column('date', sa.String(10), primary_key=True),
        sa.Column('conversations_total', sa.Integer(), server_default='0'),
        sa.Column('messages_total', sa.Integer(), server_default='0'),
        sa.Column('searches_total', sa.Integer(), server_default='0'),
        sa.Column('tours_shown', sa.Integer(), server_default='0'),
        sa.Column('avg_response_ms', sa.Integer(), server_default='0'),
        sa.Column('errors_count', sa.Integer(), server_default='0'),
        sa.Column('tokens_total', sa.Integer(), server_default='0'),
        sa.Column('unique_ips', sa.Integer(), server_default='0'),
    )


def downgrade() -> None:
    op.drop_table('daily_stats')
    op.drop_table('api_calls')
    op.drop_table('tour_searches')
    op.drop_table('messages')
    op.drop_table('conversations')
