"""add product delivery mode

Revision ID: a7b8c9d0e1f2
Revises: f1a2b3c4d5e6
Create Date: 2026-06-04 09:40:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a7b8c9d0e1f2'
down_revision: Union[str, Sequence[str], None] = 'f1a2b3c4d5e6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('products', sa.Column('delivery_mode', sa.String(length=30), nullable=False, server_default='inventory'))
    op.add_column('products', sa.Column('fixed_delivery_content', sa.Text(), nullable=True))
    op.execute("UPDATE products SET delivery_mode = 'inventory' WHERE delivery_mode IS NULL")
    op.alter_column('products', 'delivery_mode', server_default=None)


def downgrade() -> None:
    op.drop_column('products', 'fixed_delivery_content')
    op.drop_column('products', 'delivery_mode')
