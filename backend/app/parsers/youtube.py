import asyncio
from urllib.parse import parse_qs, urlparse

import httpx

from app.parsers.base import Metrics, ParserUnavailableError
from app.parsers.ytdlp_common import fetch_via_ytdlp


def _video_id(url: str) -> str:
    parsed = urlparse(url)
    if parsed.netloc.lower().endswith("youtu.be"):
        return parsed.path.strip("/").split("/")[0]
    if parsed.path.rstrip("/") == "/watch":
        return parse_qs(parsed.query).get("v", [""])[0]
    parts = parsed.path.strip("/").split("/")
    if len(parts) >= 2 and parts[0] in {"shorts", "embed", "live"}:
        return parts[1]
    return ""


async def _fetch_via_public_counter(url: str) -> Metrics:
    """Fallback for networks where Google/YouTube TLS is blocked.

    Mixerno exposes the same public view/like/comment counters and requires no
    account. The returned title and thumbnail are also used to reject an
    invalid video id instead of silently storing zeroes.
    """
    video_id = _video_id(url)
    if not video_id:
        raise ParserUnavailableError(f"Unsupported YouTube URL: {url}")

    endpoint = f"https://mixerno.space/api/youtube-video-counter/user/{video_id}"
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        response = await client.get(endpoint)
    if response.status_code != 200:
        raise ParserUnavailableError(
            f"YouTube public counter returned status {response.status_code}"
        )

    payload = response.json()
    counts = {
        item.get("value"): item.get("count")
        for item in payload.get("counts", [])
        if isinstance(item, dict)
    }
    user_fields = {
        item.get("value"): item.get("count")
        for item in payload.get("user", [])
        if isinstance(item, dict)
    }
    if not user_fields.get("name") or counts.get("views") is None:
        raise ParserUnavailableError("YouTube public counter returned incomplete data")

    return Metrics(
        likes=int(counts.get("likes") or 0),
        reposts=0,
        comments=int(counts.get("comments") or 0),
        saves=0,
        views=int(counts.get("apiviews") or counts.get("views") or 0),
    )


async def fetch(url: str) -> Metrics:
    try:
        # This endpoint is fast and remains reachable where Google domains are
        # filtered at the network level.
        return await _fetch_via_public_counter(url)
    except ParserUnavailableError:
        return await asyncio.wait_for(fetch_via_ytdlp(url), timeout=15)
