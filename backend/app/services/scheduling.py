from datetime import datetime, timedelta, timezone

from app.models.enums import Platform

PLATFORM_BASE_INTERVAL_MINUTES: dict[Platform, int] = {
    Platform.vk: 5,
    Platform.telegram: 5,
    Platform.youtube: 15,
    Platform.tiktok: 15,
    Platform.instagram: 15,
    Platform.dzen: 15,
    Platform.max_ru: 15,
    Platform.ok: 15,
}

UNAVAILABLE_RETRY_MINUTES = 30


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def next_interval_minutes(platform: Platform, post_created_at: datetime, now: datetime) -> int:
    age = _as_utc(now) - _as_utc(post_created_at)
    if age > timedelta(days=30):
        return 24 * 60
    if age > timedelta(days=7):
        return 60
    return PLATFORM_BASE_INTERVAL_MINUTES.get(platform, 15)
