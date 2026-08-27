"""add link hashtags

Revision ID: 0003
Revises: 97cd171329b3
Create Date: 2026-08-19 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003'
down_revision: Union[str, None] = '97cd171329b3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('links', sa.Column('hashtags', sa.Text(), nullable=False, server_default=''))


def downgrade() -> None:
    op.drop_column('links', 'hashtags')
