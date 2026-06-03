"""add wallet deposit message ids

Revision ID: b7c4d9e8f1a2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-03 09:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b7c4d9e8f1a2'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('wallet_transactions', sa.Column('deposit_message_id', sa.BigInteger(), nullable=True))
    op.add_column('wallet_transactions', sa.Column('deposit_qr_message_id', sa.BigInteger(), nullable=True))


def downgrade() -> None:
    op.drop_column('wallet_transactions', 'deposit_qr_message_id')
    op.drop_column('wallet_transactions', 'deposit_message_id')
