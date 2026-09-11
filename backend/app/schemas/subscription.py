from datetime import datetime

from pydantic import BaseModel, Field

from app.models.enums import Platform


class SubscriptionCreate(BaseModel):
    source_url: str  # e.g. "https://vk.com/public12345", "https://t.me/channel", "https://ok.ru/group/123"
    platform: Platform | None = None  # auto-detected if not provided
    check_interval_minutes: int = Field(default=300, ge=30, le=1440)
    backfill: bool = False


class SubscriptionOut(BaseModel):
    id: int
    platform: Platform
    source_url: str
    source_id: str
    name: str
    screen_name: str
    photo_url: str
    is_active: bool
    backfill: bool
    backfill_completed: bool
    check_interval_minutes: int
    last_checked_at: datetime | None
    message_id: int | None
    posts_count: int = 0
    active_posts_count: int = 0
    si_total: int = 0
    views_total: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class SubscriptionPostOut(BaseModel):
    id: int
    post_external_id: str
    link_id: int | None
    post_created_at: datetime
    first_seen_at: datetime
    is_tracking: bool
    likes: int = 0
    reposts: int = 0
    comments: int = 0
    views: int = 0
    si: int = 0

    class Config:
        from_attributes = True


class SubscriptionUpdate(BaseModel):
    is_active: bool | None = None
    check_interval_minutes: int | None = Field(default=None, ge=30, le=1440)
