"""add ok platform to enum

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-22

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # PostgreSQL allows adding an enum value, but the new value cannot be used
    # inside the same transaction. We autocommit the DDL statement so the value is
    # immediately available for insert.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        with op.get_context().autocommit_block():
            bind.execute(sa.text("ALTER TYPE platform ADD VALUE IF NOT EXISTS 'ok'"))


def downgrade() -> None:
    # PostgreSQL does not allow removing an enum value without recreating the
    # type and re-typing all columns. This is a small additive change, so we
    # intentionally leave the value in place on downgrade.
    pass
