from datetime import datetime

from pydantic import BaseModel, Field


class VKGroupCreate(BaseModel):
    vk_group_url: str  # e.g. "https://vk.com/public12345" or "https://vk.com/club12345" or just "public12345"
    check_interval_minutes: int = Field(default=300, ge=30, le=1440)  # 30 min to 24 hours
    backfill: bool = False  # If True, fetch all available wall posts on first check


class VKGroupOut(BaseModel):
    id: int
    vk_group_id: int
    name: str
    screen_name: str
    photo_url: str
    is_active: bool
    check_interval_minutes: int
    last_checked_at: datetime | None
    message_id: int | None
    posts_count: int = 0
    active_posts_count: int = 0
    created_at: datetime

    class Config:
        from_attributes = True


class VKGroupPostOut(BaseModel):
    id: int
    post_external_id: str
    link_id: int | None
    post_created_at: datetime
    first_seen_at: datetime
    is_tracking: bool  # True if post is less than 24h old and has active fetch jobs

    class Config:
        from_attributes = True


class VKGroupUpdate(BaseModel):
    is_active: bool | None = None
    check_interval_minutes: int | None = Field(default=None, ge=30, le=1440)
