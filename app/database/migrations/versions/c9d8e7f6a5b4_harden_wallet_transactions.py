"""harden wallet transaction reconciliation fields

Revision ID: c9d8e7f6a5b4
Revises: b7c4d9e8f1a2
Create Date: 2026-06-03 11:20:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c9d8e7f6a5b4'
down_revision: Union[str, Sequence[str], None] = 'b7c4d9e8f1a2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE wallettxstatus ADD VALUE IF NOT EXISTS 'UNDERPAID'")
    op.execute("ALTER TYPE wallettxstatus ADD VALUE IF NOT EXISTS 'REVIEW_REQUIRED'")
    op.execute("ALTER TYPE wallettxstatus ADD VALUE IF NOT EXISTS 'UNMATCHED'")
    op.execute("ALTER TYPE wallettxstatus ADD VALUE IF NOT EXISTS 'LATE_PAID'")

    op.add_column('wallet_transactions', sa.Column('provider_event_id', sa.String(length=255), nullable=True))
    op.add_column('wallet_transactions', sa.Column('provider_tx_id', sa.String(length=255), nullable=True))
    op.add_column('wallet_transactions', sa.Column('normalized_reference', sa.String(length=120), nullable=True))
    op.add_column('wallet_transactions', sa.Column('admin_actor', sa.String(length=255), nullable=True))
    op.create_index('ix_wallet_transactions_provider_event_id', 'wallet_transactions', ['provider_event_id'])
    op.create_index('ix_wallet_transactions_provider_tx_id', 'wallet_transactions', ['provider_tx_id'])
    op.create_index('ix_wallet_transactions_normalized_reference', 'wallet_transactions', ['normalized_reference'])


def downgrade() -> None:
    op.drop_index('ix_wallet_transactions_normalized_reference', table_name='wallet_transactions')
    op.drop_index('ix_wallet_transactions_provider_tx_id', table_name='wallet_transactions')
    op.drop_index('ix_wallet_transactions_provider_event_id', table_name='wallet_transactions')
    op.drop_column('wallet_transactions', 'admin_actor')
    op.drop_column('wallet_transactions', 'normalized_reference')
    op.drop_column('wallet_transactions', 'provider_tx_id')
    op.drop_column('wallet_transactions', 'provider_event_id')

    raise NotImplementedError("Downgrade for added PostgreSQL enum values is not supported automatically.")
