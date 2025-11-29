"""add sleep_sessions table

Revision ID: add_sleep_sessions
Revises: 
Create Date: 2025-03-09
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
import uuid

# revision identifiers, used by Alembic.
revision = 'add_sleep_sessions'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'sleep_sessions',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
        sa.Column('user_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('users.id', ondelete='CASCADE'), nullable=False, index=True),
        sa.Column('provider', sa.String(), nullable=False, index=True),
        sa.Column('daily_sleep_id', sa.BigInteger(), nullable=False, index=True),
        sa.Column('calendar_date', sa.Date(), nullable=False, index=True),
        sa.Column('ingest_run_id', postgresql.UUID(as_uuid=True), sa.ForeignKey('ingest_runs.id', ondelete='SET NULL'), nullable=True),
        sa.Column('summary_json', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    )
    op.create_index('ix_sleep_sessions_user_provider_sleep', 'sleep_sessions', ['user_id', 'provider', 'daily_sleep_id'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_sleep_sessions_user_provider_sleep', table_name='sleep_sessions')
    op.drop_table('sleep_sessions')
