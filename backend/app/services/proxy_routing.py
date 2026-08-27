"""Centralized proxy routing for different platforms."""

from app.core.config import settings
from app.services.proxy import normalize_proxy


def get_proxy_for_platform(platform: str) -> str | None:
    """Get the appropriate proxy for a given platform.

    NON_RU platforms (TikTok, Instagram, Telegram) use NON_RU_PROXY.
    RU platforms (Dzen, OK) use RU_PROXY.
    Other platforms use no proxy.

    Returns normalized proxy URL or None.
    """
    platform_lower = platform.lower()

    # NON_RU routing
    if platform_lower in ("tiktok", "instagram", "telegram"):
        return normalize_proxy(settings.non_ru_proxy)

    # RU routing
    if platform_lower in ("dzen", "ok", "odnoklassniki"):
        return normalize_proxy(settings.ru_proxy)

    # No proxy for VK, YouTube, MAX, etc.
    return None
