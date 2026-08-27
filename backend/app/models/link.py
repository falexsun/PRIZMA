from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Platform


class Link(Base):
    __tablename__ = "links"
    __table_args__ = (UniqueConstraint("message_id", "url_normalized", name="uq_link_message_url"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), nullable=False, index=True)
    url_raw: Mapped[str] = mapped_column(String(2048), nullable=False)
    url_normalized: Mapped[str] = mapped_column(String(2048), nullable=False, index=True)
    platform: Mapped[Platform] = mapped_column(
        Enum(Platform, name="platform", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    post_external_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    hashtags: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    message: Mapped["Message"] = relationship(back_populates="links")
    metrics_history: Mapped[list["LinkMetrics"]] = relationship(
        back_populates="link", cascade="all, delete-orphan", order_by="LinkMetrics.fetched_at"
    )
    fetch_jobs: Mapped[list["FetchJob"]] = relationship(back_populates="link", cascade="all, delete-orphan")
