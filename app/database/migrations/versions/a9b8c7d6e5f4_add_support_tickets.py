"""add support tickets

Revision ID: a9b8c7d6e5f4
Revises: f9a0b1c2d3e4
Create Date: 2026-06-19 10:50:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'a9b8c7d6e5f4'
down_revision = 'f9a0b1c2d3e4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'supportticketstatus') THEN
            CREATE TYPE supportticketstatus AS ENUM ('open', 'admin_replied', 'closed');
        END IF;
    END $$;
    """)
    support_ticket_status_column = postgresql.ENUM('open', 'admin_replied', 'closed', name='supportticketstatus', create_type=False)

    op.create_table(
        'support_tickets',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('subject', sa.String(length=255), nullable=True),
        sa.Column('status', support_ticket_status_column, nullable=False, server_default='open'),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('last_user_message_at', sa.DateTime(), nullable=True),
        sa.Column('last_admin_reply_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['user_id'], ['users.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_support_tickets_user_id'), 'support_tickets', ['user_id'], unique=False)
    op.create_index(op.f('ix_support_tickets_status'), 'support_tickets', ['status'], unique=False)

    op.create_table(
        'support_messages',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('ticket_id', sa.Integer(), nullable=False),
        sa.Column('sender_role', sa.String(length=20), nullable=False),
        sa.Column('sender_user_id', sa.BigInteger(), nullable=True),
        sa.Column('admin_actor', sa.String(length=255), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.ForeignKeyConstraint(['ticket_id'], ['support_tickets.id']),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_support_messages_ticket_id'), 'support_messages', ['ticket_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_support_messages_ticket_id'), table_name='support_messages')
    op.drop_table('support_messages')
    op.drop_index(op.f('ix_support_tickets_status'), table_name='support_tickets')
    op.drop_index(op.f('ix_support_tickets_user_id'), table_name='support_tickets')
    op.drop_table('support_tickets')
    sa.Enum(name='supportticketstatus').drop(op.get_bind(), checkfirst=True)
