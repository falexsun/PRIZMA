from datetime import datetime

from pydantic import BaseModel, Field, field_validator

from app.models.enums import Tone
from app.schemas.link import LinkWithMetricsOut
from app.schemas.topic import TopicOut

MAX_LINKS = 10_000


class MessageCreate(BaseModel):
    department: str
    tone: Tone
    title: str
    content_format: str
    topic_ids: list[int] = Field(default_factory=list)
    links: list[str] = Field(default_factory=list)

    @field_validator("links")
    @classmethod
    def validate_links_limit(cls, v: list[str]) -> list[str]:
        if len(v) > MAX_LINKS:
            raise ValueError(f"Too many links: max {MAX_LINKS}")
        return v


class MessageUpdate(BaseModel):
    department: str | None = None
    tone: Tone | None = None
    title: str | None = None
    content_format: str | None = None
    topic_ids: list[int] | None = None
    links_add: list[str] = Field(default_factory=list)
    link_ids_remove: list[int] = Field(default_factory=list)


class MessageListItem(BaseModel):
    id: int
    department: str
    content_format: str
    title: str
    tone: Tone
    topics: list[TopicOut]
    si_total: int = 0
    views_total: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class MessageDetail(BaseModel):
    id: int
    department: str
    content_format: str
    title: str
    tone: Tone
    topics: list[TopicOut]
    links: list[LinkWithMetricsOut]
    si_total: int = 0
    views_total: int = 0
    links_count: int = 0
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
