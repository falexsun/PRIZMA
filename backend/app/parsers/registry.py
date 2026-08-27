from collections.abc import Awaitable, Callable

from app.models.enums import Platform
from app.parsers import dzen, instagram, max_ru, ok, tiktok, telegram, vk, youtube
from app.parsers.base import Metrics

FetchFn = Callable[[str], Awaitable[Metrics]]

PARSERS: dict[Platform, FetchFn] = {
    Platform.vk: vk.fetch,
    Platform.telegram: telegram.fetch,
    Platform.youtube: youtube.fetch,
    Platform.tiktok: tiktok.fetch,
    Platform.instagram: instagram.fetch,
    Platform.dzen: dzen.fetch,
    Platform.max_ru: max_ru.fetch,
    Platform.ok: ok.fetch,
}


def get_parser(platform: Platform) -> FetchFn:
    return PARSERS[platform]
