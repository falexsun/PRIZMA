from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import Tone
from app.models.topic import message_topics


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    department: Mapped[str] = mapped_column(String(128), nullable=False)
    tone: Mapped[Tone] = mapped_column(
        Enum(Tone, name="tone", values_callable=lambda enum_cls: [e.value for e in enum_cls]),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    content_format: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )

    user: Mapped["User"] = relationship(back_populates="messages")
    topics: Mapped[list["Topic"]] = relationship(secondary=message_topics, back_populates="messages")
    links: Mapped[list["Link"]] = relationship(back_populates="message", cascade="all, delete-orphan")
    snapshot: Mapped["MessageMetricsSnapshot | None"] = relationship(
        back_populates="message", uselist=False, cascade="all, delete-orphan"
    )
