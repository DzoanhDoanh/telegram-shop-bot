"""add lucky spin logs

Revision ID: f3a4b5c6d7e8
Revises: e2f3a4b5c6d7
Create Date: 2026-06-19 15:18:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = 'f3a4b5c6d7e8'
down_revision = 'e2f3a4b5c6d7'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'luckyspinresulttype') THEN
            CREATE TYPE luckyspinresulttype AS ENUM ('WALLET_CREDIT', 'VOUCHER', 'TEXT');
        END IF;
    END $$;
    """)
    result_type = postgresql.ENUM('WALLET_CREDIT', 'VOUCHER', 'TEXT', name='luckyspinresulttype', create_type=False)
    op.create_table(
        'lucky_spin_logs',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.BigInteger(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('reward_label', sa.String(length=255), nullable=False),
        sa.Column('result_type', result_type, nullable=False),
        sa.Column('reward_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('voucher_code', sa.String(length=50), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
    )
    op.create_index('ix_lucky_spin_logs_user_id', 'lucky_spin_logs', ['user_id'], unique=False)
    op.create_index('ix_lucky_spin_logs_result_type', 'lucky_spin_logs', ['result_type'], unique=False)
    op.create_index('ix_lucky_spin_logs_created_at', 'lucky_spin_logs', ['created_at'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_lucky_spin_logs_created_at', table_name='lucky_spin_logs')
    op.drop_index('ix_lucky_spin_logs_result_type', table_name='lucky_spin_logs')
    op.drop_index('ix_lucky_spin_logs_user_id', table_name='lucky_spin_logs')
    op.drop_table('lucky_spin_logs')
    postgresql.ENUM(name='luckyspinresulttype').drop(op.get_bind(), checkfirst=True)
