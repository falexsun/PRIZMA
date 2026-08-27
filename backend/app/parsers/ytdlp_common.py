import asyncio

import yt_dlp

from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.services.hashtag_extractor import extract_hashtags

_YDL_OPTS = {
    "quiet": True,
    "no_warnings": True,
    "skip_download": True,
    "extract_flat": False,
    # Do not let a blocked video host occupy a Celery worker for minutes.
    "socket_timeout": 10,
    "retries": 0,
    "extractor_retries": 0,
}


def _extract_info(url: str) -> dict | None:
    with yt_dlp.YoutubeDL(_YDL_OPTS) as ydl:
        return ydl.extract_info(url, download=False)


_YTDLP_TIMEOUT = 30  # seconds — hard cap for any yt-dlp extraction


async def fetch_via_ytdlp(url: str) -> Metrics:
    try:
        info = await asyncio.wait_for(
            asyncio.to_thread(_extract_info, url),
            timeout=_YTDLP_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise ParserUnavailableError(f"yt-dlp extraction timed out ({_YTDLP_TIMEOUT}s): {url}")
    except yt_dlp.utils.DownloadError as exc:
        raise ParserNotFoundError(str(exc)) from exc
    except Exception as exc:
        raise ParserUnavailableError(str(exc)) from exc

    if not info or info.get("_type") == "playlist":
        raise ParserNotFoundError(f"No single-post data extracted for {url}")

    description = info.get("description") or ""
    tags_from_info = info.get("tags") or []
    hashtags = extract_hashtags(description)
    # Also add tags from metadata (YouTube provides these)
    for tag in tags_from_info:
        t = tag.lower().strip().lstrip("#")
        if t and t not in hashtags:
            hashtags.append(t)

    return Metrics(
        likes=info.get("like_count") or 0,
        reposts=info.get("repost_count") or 0,
        comments=info.get("comment_count") or 0,
        # yt-dlp maps TikTok's collectCount to save_count (favorites/saves).
        saves=info.get("save_count") or 0,
        views=info.get("view_count") or 0,
        hashtags=hashtags,
    )
