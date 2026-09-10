"""add vk_groups and vk_group_posts

Revision ID: 0005
Revises: 0004
Create Date: 2026-08-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vk_groups",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("vk_group_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("screen_name", sa.String(255), nullable=False, server_default=""),
        sa.Column("photo_url", sa.String(1024), nullable=False, server_default=""),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true()),
        sa.Column("backfill", sa.Boolean(), server_default=sa.false()),
        sa.Column("backfill_completed", sa.Boolean(), server_default=sa.false()),
        sa.Column("check_interval_minutes", sa.Integer(), server_default="300"),
        sa.Column("last_checked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_vk_groups_user_id", "vk_groups", ["user_id"])
    op.create_index("ix_vk_groups_message_id", "vk_groups", ["message_id"])

    op.create_table(
        "vk_group_posts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("vk_group_id", sa.Integer(), sa.ForeignKey("vk_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("post_external_id", sa.String(64), nullable=False),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("links.id", ondelete="SET NULL"), nullable=True),
        sa.Column("post_created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_vk_group_posts_vk_group_id", "vk_group_posts", ["vk_group_id"])
    op.create_index("ix_vk_group_posts_link_id", "vk_group_posts", ["link_id"])
    op.create_unique_constraint(
        "uq_vk_group_post", "vk_group_posts", ["vk_group_id", "post_external_id"]
    )


def downgrade() -> None:
    op.drop_table("vk_group_posts")
    op.drop_table("vk_groups")
