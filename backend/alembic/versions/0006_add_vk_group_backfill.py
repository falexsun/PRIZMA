"""add backfill columns to vk_groups

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("vk_groups", sa.Column("backfill", sa.Boolean(), server_default=sa.false()))
    op.add_column("vk_groups", sa.Column("backfill_completed", sa.Boolean(), server_default=sa.false()))


def downgrade() -> None:
    op.drop_column("vk_groups", "backfill_completed")
    op.drop_column("vk_groups", "backfill")
