"""add product quantity controls

Revision ID: f1a2b3c4d5e6
Revises: c9d8e7f6a5b4
Create Date: 2026-06-03 16:25:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f1a2b3c4d5e6'
down_revision: Union[str, Sequence[str], None] = 'c9d8e7f6a5b4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('allow_quantity_selection', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('products', sa.Column('min_quantity', sa.Integer(), nullable=False, server_default='1'))
    op.add_column('products', sa.Column('max_quantity', sa.Integer(), nullable=False, server_default='1'))
    op.execute("UPDATE products SET allow_quantity_selection = FALSE, min_quantity = 1, max_quantity = 1")
    op.alter_column('products', 'allow_quantity_selection', server_default=None)
    op.alter_column('products', 'min_quantity', server_default=None)
    op.alter_column('products', 'max_quantity', server_default=None)


def downgrade() -> None:
    op.drop_column('products', 'max_quantity')
    op.drop_column('products', 'min_quantity')
    op.drop_column('products', 'allow_quantity_selection')
