import asyncio
import time

import httpx
import redis
from urllib.parse import urlparse

from app.core.config import settings
from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.services.hashtag_extractor import extract_hashtags
from app.services.url_normalize import extract_post_external_id
from app.models.enums import Platform

VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.199"

# Distributed rate limiter via Redis — shared across all Celery worker processes.
# VK allows ~3 req/sec; we use 500ms minimum interval (2 req/sec) for safety.
_VK_RATE_KEY = "vk:rate_limit:last_ts"
_VK_MIN_INTERVAL = 0.5  # seconds between requests (2 req/sec, safe margin under 3)


def _vk_rate_limit_sync() -> None:
    """Wait until a rate-limit slot is available (shared across all workers via Redis)."""
    r = redis.from_url(settings.redis_url, decode_responses=True)
    for _ in range(40):  # max ~2 seconds of waiting
        now = time.time()
        last = float(r.get(_VK_RATE_KEY) or 0)
        if now - last >= _VK_MIN_INTERVAL:
            r.set(_VK_RATE_KEY, now, ex=60)
            return
        time.sleep(0.05)


def _is_video_or_clip(normalized_url: str) -> bool:
    path = urlparse(normalized_url).path.lstrip("/")
    return path.startswith("video") or path.startswith("clip")


async def _fetch_via_html(url: str) -> Metrics:
    """Fallback: scrape VK public page HTML for metrics (no token required)."""
    proxy = get_proxy_for_platform("vk")
    async with httpx.AsyncClient(timeout=15, follow_redirects=True, proxy=proxy) as client:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})

    if response.status_code == 404:
        raise ParserNotFoundError(f"VK post not found: {url}")
    if response.status_code != 200:
        raise ParserUnavailableError(f"VK HTTP error: {response.status_code}")

    html = response.text
    counts = extract_interaction_counts(html)
    hashtags = extract_hashtags(html)

    if not counts or all(v == 0 for v in counts.values()):
        raise ParserUnavailableError("VK_HTML_NO_METRICS: Could not extract metrics from VK page HTML")

    return Metrics(
        likes=counts.get("likes", 0),
        reposts=counts.get("reposts", 0),
        comments=counts.get("comments", 0),
        saves=0,
        views=counts.get("views", 0),
        hashtags=hashtags,
    )


async def fetch(url: str) -> Metrics:
    post_id = extract_post_external_id(url, Platform.vk)
    if not post_id:
        raise ParserNotFoundError(f"Cannot extract VK post id from {url}")

    vk_token = settings.vk_user_token or settings.vk_service_token
    if not vk_token:
        # Try HTML fallback
        return await _fetch_via_html(url)

    # Clips and regular videos aren't wall posts - wall.getById doesn't know about
    # them, they have to be fetched via video.get instead.
    is_video = _is_video_or_clip(url)
    method = "video.get" if is_video else "wall.getById"
    id_param = "videos" if is_video else "posts"

    params = {
        id_param: post_id,
        "access_token": vk_token,
        "v": VK_API_VERSION,
    }

    await asyncio.to_thread(_vk_rate_limit_sync)

    # Explicit timeout breakdown: connect in 3s, read in 7s. Prevents a hung
    # connection from occupying a worker and burning through rate-limit tokens.
    timeout = httpx.Timeout(connect=3.0, read=7.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{VK_API_BASE}/{method}", params=params)
        response.raise_for_status()
        data = response.json()

    if "error" in data:
        error_msg = data["error"].get("error_msg", "")
        error_code = data["error"].get("error_code", 0)
        # Rate limit errors should be retried later
        if error_code == 6 or "rate" in error_msg.lower() or "too many" in error_msg.lower():
            raise ParserUnavailableError(f"VK API error: {error_msg}")
        raise ParserUnavailableError(f"VK API error: {error_msg}")

    response_data = data.get("response", [])
    # Both endpoints have returned either a flat list of items, or (as of v5.199)
    # a dict shaped like {"items": [...], "reaction_sets": [...]} - handle both.
    items = response_data.get("items", []) if isinstance(response_data, dict) else response_data
    if not items:
        raise ParserNotFoundError(f"VK post not found: {post_id}")

    item = items[0]

    text = item.get("text", "")
    hashtags = extract_hashtags(text)

    if is_video:
        # video.get returns views/comments as plain integers, unlike wall posts
        # which nest them as {"count": N}.
        return Metrics(
            likes=item.get("likes", {}).get("count", 0),
            reposts=0,
            comments=item.get("comments", 0) or 0,
            saves=0,
            views=item.get("views", 0) or 0,
            hashtags=hashtags,
        )

    return Metrics(
        likes=item.get("likes", {}).get("count", 0),
        reposts=item.get("reposts", {}).get("count", 0),
        comments=item.get("comments", {}).get("count", 0),
        saves=0,
        views=item.get("views", {}).get("count", 0),
        hashtags=hashtags,
    )
