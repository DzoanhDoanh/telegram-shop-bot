"""add wallet transactions and payment config fields

Revision ID: a1b2c3d4e5f6
Revises: 0b8eb92f5ad1
Create Date: 2026-06-01 15:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = '0b8eb92f5ad1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Add wallet_balance to users
    op.add_column('users', sa.Column('wallet_balance', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'))

    # Create wallet_transactions table
    op.create_table('wallet_transactions',
    sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
    sa.Column('user_id', sa.BigInteger(), nullable=False),
    sa.Column('tx_type', sa.Enum('DEPOSIT', 'PURCHASE', 'REFUND', 'ADMIN_CREDIT', 'ADMIN_DEBIT', name='wallettxtype'), nullable=False),
    sa.Column('amount', sa.Numeric(precision=12, scale=2), nullable=False),
    sa.Column('status', sa.Enum('PENDING', 'SUCCESS', 'FAILED', 'CANCELLED', name='wallettxstatus'), nullable=False),
    sa.Column('reference', sa.String(length=100), nullable=True),
    sa.Column('provider', sa.String(length=50), nullable=True),
    sa.Column('raw_payload', sa.JSON(), nullable=True),
    sa.Column('note', sa.Text(), nullable=True),
    sa.Column('created_at', sa.DateTime(), nullable=False),
    sa.Column('completed_at', sa.DateTime(), nullable=True),
    sa.ForeignKeyConstraint(['user_id'], ['users.id'], ),
    sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_wallet_transactions_reference', 'wallet_transactions', ['reference'])

    # Add new columns to payment_configs
    op.add_column('payment_configs', sa.Column('vietqr_bank_code', sa.String(length=20), nullable=True))
    op.add_column('payment_configs', sa.Column('webhook_secret', sa.String(length=255), nullable=True))
    op.add_column('payment_configs', sa.Column('webhook_provider', sa.String(length=50), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('payment_configs', 'webhook_provider')
    op.drop_column('payment_configs', 'webhook_secret')
    op.drop_column('payment_configs', 'vietqr_bank_code')
    op.drop_index('ix_wallet_transactions_reference', table_name='wallet_transactions')
    op.drop_table('wallet_transactions')
    sa.Enum(name='wallettxstatus').drop(op.get_bind())
    sa.Enum(name='wallettxtype').drop(op.get_bind())
    op.drop_column('users', 'wallet_balance')
