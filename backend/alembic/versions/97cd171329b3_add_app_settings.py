"""add app_settings

Revision ID: 97cd171329b3
Revises: 0002
Create Date: 2026-07-22 16:40:13.079097

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '97cd171329b3'
down_revision: Union[str, None] = '0002'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'app_settings',
        sa.Column('key', sa.String(length=255), nullable=False),
        sa.Column('value', sa.Text(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('key')
    )


def downgrade() -> None:
    op.drop_table('app_settings')
