"""add vouchers

Revision ID: c1d2e3f4a5b6
Revises: b1c2d3e4f5a6
Create Date: 2026-06-19 14:25:00.000000
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = 'c1d2e3f4a5b6'
down_revision = 'b1c2d3e4f5a6'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    DO $$
    BEGIN
        IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'voucherdiscounttype') THEN
            CREATE TYPE voucherdiscounttype AS ENUM ('PERCENT', 'AMOUNT');
        END IF;
    END $$;
    """)
    discount_type = postgresql.ENUM('PERCENT', 'AMOUNT', name='voucherdiscounttype', create_type=False)
    op.create_table(
        'vouchers',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('code', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('discount_type', discount_type, nullable=False),
        sa.Column('discount_value', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('min_order_amount', sa.Numeric(12, 2), nullable=False, server_default='0'),
        sa.Column('max_discount_amount', sa.Numeric(12, 2), nullable=True),
        sa.Column('usage_limit', sa.Integer(), nullable=True),
        sa.Column('used_count', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('starts_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        sa.Column('applies_product_id', sa.Integer(), nullable=True),
        sa.Column('applies_category_id', sa.Integer(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['applies_category_id'], ['categories.id']),
        sa.ForeignKeyConstraint(['applies_product_id'], ['products.id']),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index('ix_vouchers_code', 'vouchers', ['code'], unique=True)


def downgrade() -> None:
    op.drop_index('ix_vouchers_code', table_name='vouchers')
    op.drop_table('vouchers')
    postgresql.ENUM(name='voucherdiscounttype').drop(op.get_bind(), checkfirst=True)
