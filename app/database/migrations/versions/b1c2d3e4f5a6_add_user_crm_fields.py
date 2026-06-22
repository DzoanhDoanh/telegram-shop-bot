"""add user crm fields

Revision ID: b1c2d3e4f5a6
Revises: a9b8c7d6e5f4
Create Date: 2026-06-19 11:50:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = 'b1c2d3e4f5a6'
down_revision = 'a9b8c7d6e5f4'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('crm_tag', sa.String(length=100), nullable=True))
    op.add_column('users', sa.Column('internal_note', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('users', 'internal_note')
    op.drop_column('users', 'crm_tag')
