from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Platform


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    message_id: Mapped[int | None] = mapped_column(
        ForeignKey("messages.id", ondelete="SET NULL"), nullable=True, index=True
    )
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, name="platform", values_callable=lambda enum_cls: [e.value for e in enum_cls], create_type=False),
        nullable=False,
    )
    source_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    source_id: Mapped[str] = mapped_column(String(255), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    screen_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    photo_url: Mapped[str] = mapped_column(String(1024), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    backfill: Mapped[bool] = mapped_column(Boolean, default=False)
    backfill_completed: Mapped[bool] = mapped_column(Boolean, default=False)
    check_interval_minutes: Mapped[int] = mapped_column(Integer, default=300)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    user: Mapped["User"] = relationship()
    message: Mapped["Message | None"] = relationship()
    posts: Mapped[list["SubscriptionPost"]] = relationship(
        back_populates="subscription", cascade="all, delete-orphan",
        order_by="SubscriptionPost.post_created_at.desc()",
    )


class SubscriptionPost(Base):
    __tablename__ = "subscription_posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    subscription_id: Mapped[int] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    post_external_id: Mapped[str] = mapped_column(String(255), nullable=False)
    link_id: Mapped[int | None] = mapped_column(
        ForeignKey("links.id", ondelete="SET NULL"), nullable=True, index=True
    )
    post_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    subscription: Mapped["Subscription"] = relationship(back_populates="posts")
    link: Mapped["Link | None"] = relationship()
