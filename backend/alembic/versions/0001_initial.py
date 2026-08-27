"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-17

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    user_role = sa.Enum("admin", "org_user", name="user_role")
    tone = sa.Enum("positive", "neutral", "negative", name="tone")
    platform = sa.Enum("vk", "telegram", "youtube", "tiktok", "instagram", "dzen", "max", name="platform")
    fetch_status = sa.Enum("pending", "in_progress", "success", "failed", "unavailable", name="fetch_status")

    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("login", sa.String(64), nullable=False, unique=True),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("org_name", sa.String(128), nullable=False),
        sa.Column("department", sa.String(128), nullable=False),
        sa.Column("role", user_role, nullable=False, server_default="org_user"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_login", "users", ["login"])

    op.create_table(
        "topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(128), nullable=False, unique=True),
    )

    op.create_table(
        "messages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("department", sa.String(128), nullable=False),
        sa.Column("tone", tone, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("content_format", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_messages_user_id", "messages", ["user_id"])

    op.create_table(
        "message_topics",
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("topics.id", ondelete="CASCADE"), primary_key=True),
    )

    op.create_table(
        "links",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), nullable=False),
        sa.Column("url_raw", sa.String(2048), nullable=False),
        sa.Column("url_normalized", sa.String(2048), nullable=False),
        sa.Column("platform", platform, nullable=False),
        sa.Column("post_external_id", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("message_id", "url_normalized", name="uq_link_message_url"),
    )
    op.create_index("ix_links_message_id", "links", ["message_id"])
    op.create_index("ix_links_url_normalized", "links", ["url_normalized"])

    op.create_table(
        "link_metrics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("likes", sa.Integer(), server_default="0"),
        sa.Column("reposts", sa.Integer(), server_default="0"),
        sa.Column("comments", sa.Integer(), server_default="0"),
        sa.Column("saves", sa.Integer(), server_default="0"),
        sa.Column("views", sa.Integer(), server_default="0"),
        sa.Column("si", sa.Integer(), server_default="0"),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_link_metrics_link_id", "link_metrics", ["link_id"])
    op.create_index("ix_link_metrics_fetched_at", "link_metrics", ["fetched_at"])

    op.create_table(
        "message_metrics_snapshots",
        sa.Column("message_id", sa.Integer(), sa.ForeignKey("messages.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("si_total", sa.Integer(), server_default="0"),
        sa.Column("views_total", sa.Integer(), server_default="0"),
        sa.Column("links_count", sa.Integer(), server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_table(
        "fetch_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("link_id", sa.Integer(), sa.ForeignKey("links.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", fetch_status, nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer(), server_default="0"),
        sa.Column("last_error", sa.String(1024), nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_fetch_jobs_link_id", "fetch_jobs", ["link_id"])
    op.create_index("ix_fetch_jobs_next_run_at", "fetch_jobs", ["next_run_at"])


def downgrade() -> None:
    op.drop_table("fetch_jobs")
    op.drop_table("message_metrics_snapshots")
    op.drop_table("link_metrics")
    op.drop_table("links")
    op.drop_table("message_topics")
    op.drop_table("messages")
    op.drop_table("topics")
    op.drop_table("users")

    sa.Enum(name="fetch_status").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="platform").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="tone").drop(op.get_bind(), checkfirst=True)
    sa.Enum(name="user_role").drop(op.get_bind(), checkfirst=True)
