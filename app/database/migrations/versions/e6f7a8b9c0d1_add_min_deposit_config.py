"""add minimum deposit config

Revision ID: e6f7a8b9c0d1
Revises: d4e5f6a7b8c9
Create Date: 2026-06-16 09:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a7b8c9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('payment_configs', sa.Column('min_deposit_enabled', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('payment_configs', sa.Column('min_deposit_amount', sa.Numeric(precision=12, scale=2), nullable=False, server_default='0'))
    op.alter_column('payment_configs', 'min_deposit_enabled', server_default=None)
    op.alter_column('payment_configs', 'min_deposit_amount', server_default=None)


def downgrade() -> None:
    op.drop_column('payment_configs', 'min_deposit_amount')
    op.drop_column('payment_configs', 'min_deposit_enabled')
