"""Platform-specific source discovery: fetch recent posts from a social media source."""

import time
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.models.enums import Platform


@dataclass
class DiscoveredPost:
    external_id: str
    url: str
    timestamp: float  # unix epoch


# ---------------------------------------------------------------------------
# VK
# ---------------------------------------------------------------------------

VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.199"


def _vk_rate_limit() -> None:
    import redis
    r = redis.from_url(settings.redis_url, decode_responses=True)
    for _ in range(40):
        now = time.time()
        last = float(r.get("vk:rate_limit:last_ts") or 0)
        if now - last >= 0.5:
            r.set("vk:rate_limit:last_ts", now, ex=60)
            return
        time.sleep(0.05)


def _vk_wall_get(owner_id: int, count: int = 20, offset: int = 0) -> list[dict]:
    vk_token = settings.vk_user_token or settings.vk_service_token
    if not vk_token:
        raise RuntimeError("VK token is not configured")
    _vk_rate_limit()
    params = {
        "owner_id": owner_id,
        "count": count,
        "offset": offset,
        "access_token": vk_token,
        "v": VK_API_VERSION,
    }
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(f"{VK_API_BASE}/wall.get", params=params, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"VK API error: {data['error'].get('error_msg', '')}")
    rd = data.get("response", {})
    return rd.get("items", []) if isinstance(rd, dict) else rd


def _resolve_vk_owner_id(source_id: str) -> int:
    """Resolve VK screen name or numeric ID to a numeric owner_id for wall.get."""
    if source_id.lstrip("-").isdigit():
        return int(source_id)
    # Screen name - resolve via groups.getById
    vk_token = settings.vk_user_token or settings.vk_service_token
    _vk_rate_limit()
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(f"{VK_API_BASE}/groups.getById", params={
        "group_ids": source_id, "access_token": vk_token, "v": VK_API_VERSION,
    }, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        raise RuntimeError(f"VK API error: {data['error'].get('error_msg', '')}")
    groups = data.get("response", {}).get("groups", [])
    if not groups:
        raise RuntimeError(f"VK group not found: {source_id}")
    return groups[0]["id"]


def discover_vk(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Fetch wall posts from VK group (negative id) or user (positive id)."""
    owner_id = _resolve_vk_owner_id(source_id)
    all_items: list[dict] = []
    if backfill:
        offset = 0
        for _ in range(100):
            items = _vk_wall_get(owner_id, count=100, offset=offset)
            if not items:
                break
            all_items.extend(items)
            if len(items) < 100:
                break
            offset += 100
    else:
        all_items = _vk_wall_get(owner_id, count=20)

    posts: list[DiscoveredPost] = []
    for item in all_items:
        post_id = item.get("id", 0)
        owner = item.get("owner_id", owner_id)
        ext_id = f"{owner}_{post_id}"
        date = item.get("date", 0)
        posts.append(DiscoveredPost(
            external_id=ext_id,
            url=f"https://vk.com/wall{ext_id}",
            timestamp=float(date),
        ))
    return posts


# ---------------------------------------------------------------------------
# OK (Одноклассники)
# ---------------------------------------------------------------------------

def _ok_api_call(method: str, params: dict) -> dict:
    ok_token = getattr(settings, "ok_service_token", "") or ""
    if not ok_token:
        raise RuntimeError("OK token is not configured")
    params.update({
        "access_token": ok_token,
        "format": "JSON",
    })
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(f"https://api.ok.ru/fb.do", params=params, timeout=timeout)
    resp.raise_for_status()
    return resp.json()


def discover_ok(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Fetch recent posts from OK group/user via group.getWallPosts or similar."""
    # OK API: group.getWallPosts requires group ID
    count = 100 if backfill else 20
    data = _ok_api_call("group.getWallPosts", {
        "gid": source_id,
        "count": str(count),
        "fields": "created_ms",
    })
    posts_data = data.get("posts", data if isinstance(data, list) else [])
    result: list[DiscoveredPost] = []
    for post in posts_data:
        post_id = str(post.get("id", ""))
        created = post.get("created_ms", 0)
        if created:
            ts = float(created) / 1000.0
        else:
            ts = float(post.get("created", 0))
        result.append(DiscoveredPost(
            external_id=post_id,
            url=f"https://ok.ru/group/{source_id}/topic/{post_id}",
            timestamp=ts,
        ))
    return result


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

def discover_telegram(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Scrape t.me/<channel> preview page for recent posts."""
    url = f"https://t.me/s/{source_id}"
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    html = resp.text

    import re
    # Extract post IDs from data-post attributes
    post_matches = re.findall(r'data-post="([^"]+/(\d+))"', html)
    if not post_matches:
        # Try alternative pattern
        post_matches = re.findall(r'href="[^"]*?/(\d+)"', html)

    result: list[DiscoveredPost] = []
    seen: set[str] = set()
    limit = 100 if backfill else 30
    for match in post_matches[:limit]:
        if isinstance(match, tuple):
            post_id = match[1]
        else:
            post_id = match
        if post_id in seen:
            continue
        seen.add(post_id)
        result.append(DiscoveredPost(
            external_id=post_id,
            url=f"https://t.me/{source_id}/{post_id}",
            timestamp=0,  # Telegram doesn't expose timestamps easily; use 0 to mean "unknown"
        ))
    return result


# ---------------------------------------------------------------------------
# YouTube
# ---------------------------------------------------------------------------

def discover_youtube(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Fetch recent uploads from a YouTube channel via API."""
    api_key = settings.youtube_api_key
    if not api_key:
        raise RuntimeError("YouTube API key is not configured")

    # Get channel uploads playlist
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get("https://www.googleapis.com/youtube/v3/channels", params={
        "part": "contentDetails",
        "id": source_id,
        "key": api_key,
    }, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()
    items = data.get("items", [])
    if not items:
        return []

    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Get videos from uploads playlist
    count = 50 if backfill else 10
    resp = httpx.get("https://www.googleapis.com/youtube/v3/playlistItems", params={
        "part": "snippet",
        "playlistId": uploads_playlist,
        "maxResults": str(count),
        "key": api_key,
    }, timeout=timeout)
    resp.raise_for_status()
    data = resp.json()

    result: list[DiscoveredPost] = []
    for item in data.get("items", []):
        snippet = item.get("snippet", {})
        video_id = snippet.get("resourceId", {}).get("videoId", "")
        published = snippet.get("publishedAt", "")
        ts = 0.0
        if published:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                ts = dt.timestamp()
            except Exception:
                pass
        result.append(DiscoveredPost(
            external_id=video_id,
            url=f"https://www.youtube.com/watch?v={video_id}",
            timestamp=ts,
        ))
    return result


# ---------------------------------------------------------------------------
# TikTok
# ---------------------------------------------------------------------------

def discover_tiktok(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Scrape TikTok profile page for recent video links."""
    url = f"https://www.tiktok.com/@{source_id}"
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    html = resp.text

    import re
    video_matches = re.findall(r'/video/(\d+)', html)
    seen: set[str] = set()
    limit = 50 if backfill else 15
    result: list[DiscoveredPost] = []
    for vid in video_matches[:limit]:
        if vid in seen:
            continue
        seen.add(vid)
        result.append(DiscoveredPost(
            external_id=vid,
            url=f"https://www.tiktok.com/@{source_id}/video/{vid}",
            timestamp=0,
        ))
    return result


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

def discover_instagram(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Scrape Instagram profile for recent post/reel links."""
    url = f"https://www.instagram.com/{source_id}/"
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    html = resp.text

    import re
    post_ids = re.findall(r'"shortcode":"([A-Za-z0-9_-]+)"', html)
    if not post_ids:
        post_ids = re.findall(r'/p/([A-Za-z0-9_-]+)', html)
    if not post_ids:
        post_ids = re.findall(r'/reel/([A-Za-z0-9_-]+)', html)

    seen: set[str] = set()
    limit = 30 if backfill else 12
    result: list[DiscoveredPost] = []
    for sid in post_ids[:limit]:
        if sid in seen:
            continue
        seen.add(sid)
        # Determine if it's a reel or post by checking context
        result.append(DiscoveredPost(
            external_id=sid,
            url=f"https://www.instagram.com/p/{sid}/",
            timestamp=0,
        ))
    return result


# ---------------------------------------------------------------------------
# Dzen
# ---------------------------------------------------------------------------

def discover_dzen(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Scrape Dzen author page for recent posts."""
    url = f"https://dzen.ru/{source_id}"
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    html = resp.text

    import re
    # Dzen article IDs in URLs like /id/XXXXX or article links
    article_ids = re.findall(r'"articleId":"([^"]+)"', html)
    if not article_ids:
        article_ids = re.findall(r'/article/([a-f0-9]+)', html)

    seen: set[str] = set()
    limit = 30 if backfill else 10
    result: list[DiscoveredPost] = []
    for aid in article_ids[:limit]:
        if aid in seen:
            continue
        seen.add(aid)
        result.append(DiscoveredPost(
            external_id=aid,
            url=f"https://dzen.ru/a/{aid}",
            timestamp=0,
        ))
    return result


# ---------------------------------------------------------------------------
# MAX
# ---------------------------------------------------------------------------

def discover_max(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Scrape MAX profile for recent posts."""
    url = f"https://max.ru/{source_id}"
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(url, timeout=timeout, follow_redirects=True,
                     headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    html = resp.text

    import re
    post_ids = re.findall(r'/post/(\d+)', html)
    if not post_ids:
        post_ids = re.findall(r'"id":\s*"?(\d+)"?', html)

    seen: set[str] = set()
    limit = 30 if backfill else 10
    result: list[DiscoveredPost] = []
    for pid in post_ids[:limit]:
        if pid in seen:
            continue
        seen.add(pid)
        result.append(DiscoveredPost(
            external_id=pid,
            url=f"https://max.ru/post/{pid}",
            timestamp=0,
        ))
    return result


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

DISCOVER_HANDLERS: dict[Platform, callable] = {
    Platform.vk: discover_vk,
    Platform.ok: discover_ok,
    Platform.telegram: discover_telegram,
    Platform.youtube: discover_youtube,
    Platform.tiktok: discover_tiktok,
    Platform.instagram: discover_instagram,
    Platform.dzen: discover_dzen,
    Platform.max_ru: discover_max,
}


def discover_posts(platform: Platform, source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    handler = DISCOVER_HANDLERS.get(platform)
    if handler is None:
        raise ValueError(f"No discovery handler for platform: {platform}")
    return handler(source_id, backfill)
