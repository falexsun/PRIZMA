from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import FetchStatus


class FetchJob(Base):
    __tablename__ = "fetch_jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    link_id: Mapped[int] = mapped_column(ForeignKey("links.id", ondelete="CASCADE"), nullable=False, index=True)
    status: Mapped[FetchStatus] = mapped_column(
        Enum(FetchStatus, name="fetch_status", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
        default=FetchStatus.pending,
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    link: Mapped["Link"] = relationship(back_populates="fetch_jobs")
