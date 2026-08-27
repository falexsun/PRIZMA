import asyncio
import re
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.parsers.ytdlp_common import fetch_via_ytdlp
from app.services.hashtag_extractor import extract_hashtags
from app.services.proxy_routing import get_proxy_for_platform

RAPIDAPI_HOST = "tiktok-api23.p.rapidapi.com"
RAPIDAPI_BASE = f"https://{RAPIDAPI_HOST}"

_VIDEO_ID_RE = re.compile(r"/video/(\d+)")


async def _resolve_video_id(url: str, proxy: str | None) -> str | None:
    """Extract TikTok's numeric video id from a URL.

    Full URLs (tiktok.com/@user/video/123...) already contain the id. Short
    links (vt.tiktok.com/..., vm.tiktok.com/...) redirect to the full URL and
    have to be resolved first.
    """
    match = _VIDEO_ID_RE.search(urlparse(url).path)
    if match:
        return match.group(1)

    host = urlparse(url).netloc.lower()
    if not host.endswith("tiktok.com") or host == "www.tiktok.com" or host == "tiktok.com":
        return None

    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, proxy=proxy) as client:
            response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
    except httpx.HTTPError as exc:
        raise ParserUnavailableError(f"Could not resolve TikTok short link: {exc}") from exc

    match = _VIDEO_ID_RE.search(urlparse(str(response.url)).path)
    return match.group(1) if match else None


async def _fetch_via_rapidapi(video_id: str, proxy: str | None) -> Metrics:
    try:
        async with httpx.AsyncClient(timeout=15, proxy=proxy) as client:
            response = await client.get(
                f"{RAPIDAPI_BASE}/api/post/detail",
                params={"videoId": video_id},
                headers={
                    "x-rapidapi-host": RAPIDAPI_HOST,
                    "x-rapidapi-key": settings.tiktok_rapidapi_key,
                },
            )
    except httpx.HTTPError as exc:
        raise ParserUnavailableError(f"TikTok RapidAPI request failed: {exc}") from exc

    if response.status_code == 429:
        raise ParserUnavailableError("TikTok RapidAPI rate limit exceeded")
    if response.status_code != 200:
        raise ParserUnavailableError(f"TikTok RapidAPI returned status {response.status_code}")

    data = response.json()

    # statusCode 0 = success; anything else signals a deleted/private/missing post.
    status_code = data.get("statusCode")
    if status_code not in (0, None):
        raise ParserNotFoundError(
            f"TikTok post not found ({data.get('statusMsg') or status_code}): {video_id}"
        )

    item = (data.get("itemInfo") or {}).get("itemStruct")
    if not item:
        raise ParserNotFoundError(f"TikTok post not found: {video_id}")

    stats = item.get("statsV2") or item.get("stats") or {}
    desc = item.get("desc") or ""
    hashtags = extract_hashtags(desc)

    return Metrics(
        likes=int(stats.get("diggCount") or 0),
        reposts=int(stats.get("repostCount") or stats.get("shareCount") or 0),
        comments=int(stats.get("commentCount") or 0),
        saves=int(stats.get("collectCount") or 0),
        views=int(stats.get("playCount") or 0),
        hashtags=hashtags,
    )


def _fetch_via_tikwm_sync(url: str) -> Metrics:
    """Fetch TikTok metrics via TikWM free API (no key needed)."""
    import sys
    sys.path.insert(0, "/app")
    from tiktok_tikwm_parser import fetch_tiktok

    result, _ = fetch_tiktok(url, timeout=30, retries=2)
    desc = result.title or ""
    return Metrics(
        likes=result.likes or 0,
        reposts=result.shares or 0,
        comments=result.comments or 0,
        saves=result.saves or 0,
        views=result.views or 0,
        hashtags=extract_hashtags(desc),
    )


async def fetch(url: str) -> Metrics:
    # Strategy 1: TikWM (free, no key needed)
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_via_tikwm_sync, url),
            timeout=60,
        )
    except asyncio.TimeoutError:
        pass
    except ParserNotFoundError:
        raise
    except Exception:
        pass

    # Strategy 2: RapidAPI (fallback)
    if settings.tiktok_rapidapi_key:
        proxy = get_proxy_for_platform("tiktok")
        try:
            video_id = await _resolve_video_id(url, proxy)
            if not video_id:
                raise ParserNotFoundError(f"Could not extract TikTok video ID from {url}")
            return await _fetch_via_rapidapi(video_id, proxy)
        except ParserNotFoundError:
            raise
        except ParserUnavailableError:
            raise

    raise ParserUnavailableError(
        "TIKTOK_CONFIG_MISSING: TikTok requires TikWM (auto) or TIKTOK_RAPIDAPI_KEY."
    )
