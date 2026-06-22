"""add order voucher fields

Revision ID: d1e2f3a4b5c6
Revises: c1d2e3f4a5b6
Create Date: 2026-06-19 14:31:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'd1e2f3a4b5c6'
down_revision = 'c1d2e3f4a5b6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('orders', sa.Column('original_amount', sa.Numeric(12, 2), nullable=True))
    op.add_column('orders', sa.Column('discount_amount', sa.Numeric(12, 2), nullable=True))
    op.add_column('orders', sa.Column('voucher_code', sa.String(length=50), nullable=True))
    op.create_index('ix_orders_voucher_code', 'orders', ['voucher_code'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_orders_voucher_code', table_name='orders')
    op.drop_column('orders', 'voucher_code')
    op.drop_column('orders', 'discount_amount')
    op.drop_column('orders', 'original_amount')
