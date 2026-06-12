"""add order_code to orders

Revision ID: d4e5f6a7b8c9
Revises: a7b8c9d0e1f2
Create Date: 2026-06-12 14:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd4e5f6a7b8c9'
down_revision: Union[str, Sequence[str], None] = 'a7b8c9d0e1f2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('order_code', sa.String(length=20), nullable=True))
    op.execute("UPDATE orders SET order_code = 'DH' || LPAD(id::text, 6, '0') WHERE order_code IS NULL")
    op.alter_column('orders', 'order_code', nullable=False)
    op.create_index('ix_orders_order_code', 'orders', ['order_code'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_orders_order_code', table_name='orders')
    op.drop_column('orders', 'order_code')
