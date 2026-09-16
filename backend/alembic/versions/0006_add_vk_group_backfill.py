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
    bind = op.get_bind()
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("vk_groups")}

    if "backfill" not in existing_columns:
        op.add_column("vk_groups", sa.Column("backfill", sa.Boolean(), server_default=sa.false()))
    if "backfill_completed" not in existing_columns:
        op.add_column("vk_groups", sa.Column("backfill_completed", sa.Boolean(), server_default=sa.false()))


def downgrade() -> None:
    bind = op.get_bind()
    existing_columns = {column["name"] for column in sa.inspect(bind).get_columns("vk_groups")}

    if "backfill_completed" in existing_columns:
        op.drop_column("vk_groups", "backfill_completed")
    if "backfill" in existing_columns:
        op.drop_column("vk_groups", "backfill")
