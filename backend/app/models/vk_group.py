from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class VKGroup(Base):
    __tablename__ = "vk_groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    vk_group_id: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    screen_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    photo_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    backfill: Mapped[bool] = mapped_column(Boolean, default=False)
    backfill_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=300)  # 5 hours
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()
    message: Mapped["Message | None"] = relationship()
    posts: Mapped[list["VKGroupPost"]] = relationship(
        back_populates="group", cascade="all, delete-orphan", order_by="VKGroupPost.post_created_at.desc()"
    )


class VKGroupPost(Base):
    __tablename__ = "vk_group_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    vk_group_id: Mapped[int] = mapped_column(
        ForeignKey("vk_groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    post_external_id: Mapped[str] = mapped_column(String(64), nullable=False)
    link_id: Mapped[int | None] = mapped_column(
        ForeignKey("links.id", ondelete="SET NULL"), nullable=True, index=True
    )
    post_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    group: Mapped["VKGroup"] = relationship(back_populates="posts")
    link: Mapped["Link | None"] = relationship()
