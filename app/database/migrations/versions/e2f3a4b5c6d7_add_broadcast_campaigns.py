"""add broadcast campaigns

Revision ID: e2f3a4b5c6d7
Revises: d1e2f3a4b5c6
Create Date: 2026-06-19 15:05:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'e2f3a4b5c6d7'
down_revision = 'd1e2f3a4b5c6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'broadcastcampaignstatus') THEN
            CREATE TYPE broadcastcampaignstatus AS ENUM ('DRAFT', 'SENT', 'PARTIAL', 'FAILED');
        END IF;
    END $$;
    """)
    status_enum = postgresql.ENUM('DRAFT', 'SENT', 'PARTIAL', 'FAILED', name='broadcastcampaignstatus', create_type=False)
    op.create_table(
        'broadcast_campaigns',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('segment', sa.String(length=50), nullable=False),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('recipient_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('sent_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('failed_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('status', status_enum, nullable=False, server_default='DRAFT'),
        sa.Column('admin_actor', sa.String(length=255), nullable=True),
        sa.Column('notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('sent_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_broadcast_campaigns_segment', 'broadcast_campaigns', ['segment'], unique=False)
    op.create_index('ix_broadcast_campaigns_status', 'broadcast_campaigns', ['status'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_broadcast_campaigns_status', table_name='broadcast_campaigns')
    op.drop_index('ix_broadcast_campaigns_segment', table_name='broadcast_campaigns')
    op.drop_table('broadcast_campaigns')
    postgresql.ENUM(name='broadcastcampaignstatus').drop(op.get_bind(), checkfirst=True)
