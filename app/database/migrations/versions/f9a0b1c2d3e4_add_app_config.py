"""add app config

Revision ID: f9a0b1c2d3e4
Revises: d4e5f6a7b8c9
Create Date: 2026-06-19 10:35:00.000000
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f9a0b1c2d3e4'
down_revision = 'e6f7a8b9c0d1'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'app_configs',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('shop_display_name', sa.String(length=255), nullable=True),
        sa.Column('support_username', sa.String(length=255), nullable=True),
        sa.Column('welcome_text', sa.Text(), nullable=True),
        sa.Column('help_text', sa.Text(), nullable=True),
        sa.Column('terms_text', sa.Text(), nullable=True),
        sa.Column('support_text', sa.Text(), nullable=True),
        sa.Column('maintenance_mode', sa.Boolean(), nullable=False, server_default=sa.text('false')),
        sa.Column('enable_product_search', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('enable_support_forwarding', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('enable_lucky_spin', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('show_terms_button', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('show_help_button', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.text('true')),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('now()')),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade() -> None:
    op.drop_table('app_configs')
