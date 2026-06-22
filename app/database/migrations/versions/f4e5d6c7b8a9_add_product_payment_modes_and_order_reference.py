"""add product payment modes and order transfer reference

Revision ID: f4e5d6c7b8a9
Revises: a4b5c6d7e8f9
Create Date: 2026-06-22 11:10:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'f4e5d6c7b8a9'
down_revision = 'a4b5c6d7e8f9'
branch_labels = None
depends_on = None


PAYMENT_MODE_DEFAULT = 'wallet_only'


def upgrade() -> None:
    op.add_column('products', sa.Column('payment_mode', sa.String(length=30), nullable=False, server_default=PAYMENT_MODE_DEFAULT))
    op.add_column('orders', sa.Column('bank_transfer_reference_normalized', sa.String(length=100), nullable=True))
    op.execute(f"UPDATE products SET payment_mode = '{PAYMENT_MODE_DEFAULT}' WHERE payment_mode IS NULL")
    op.alter_column('products', 'payment_mode', server_default=None)
    op.create_index('ix_orders_bank_transfer_reference_normalized', 'orders', ['bank_transfer_reference_normalized'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_orders_bank_transfer_reference_normalized', table_name='orders')
    op.drop_column('orders', 'bank_transfer_reference_normalized')
    op.drop_column('products', 'payment_mode')
