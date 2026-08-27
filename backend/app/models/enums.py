import enum


class UserRole(str, enum.Enum):
    admin = "admin"
    org_user = "org_user"


class Tone(str, enum.Enum):
    positive = "positive"
    neutral = "neutral"
    negative = "negative"


class Platform(str, enum.Enum):
    vk = "vk"
    telegram = "telegram"
    youtube = "youtube"
    tiktok = "tiktok"
    instagram = "instagram"
    dzen = "dzen"
    max_ru = "max"
    ok = "ok"


class FetchStatus(str, enum.Enum):
    pending = "pending"
    in_progress = "in_progress"
    success = "success"
    failed = "failed"
    unavailable = "unavailable"
