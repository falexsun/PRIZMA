from datetime import datetime

from pydantic import BaseModel

from app.models.enums import Platform


class LinkOut(BaseModel):
    id: int
    url_raw: str
    url_normalized: str
    platform: Platform
    hashtags: str = ""
    created_at: datetime

    class Config:
        from_attributes = True


class LinkMetricsOut(BaseModel):
    likes: int
    reposts: int
    comments: int
    saves: int
    views: int
    si: int
    fetched_at: datetime

    class Config:
        from_attributes = True


class LinkWithMetricsOut(LinkOut):
    latest_metrics: LinkMetricsOut | None = None
