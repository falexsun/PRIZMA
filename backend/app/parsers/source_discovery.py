"""Platform-specific source discovery: fetch recent posts from a social media source."""

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.core.config import settings
from app.models.enums import Platform
from app.services.proxy_routing import get_proxy_for_platform


@dataclass
class DiscoveredPost:
    external_id: str
    url: str
    timestamp: float  # unix epoch


class _QuietYtdlpLogger:
    def debug(self, msg: str) -> None:
        pass

    def warning(self, msg: str) -> None:
        pass

    def error(self, msg: str) -> None:
        pass


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
        error_msg = data["error"].get("error_msg", "")
        error_code = data["error"].get("error_code", 0)
        # Rate limit: wait and retry once
        if error_code == 6:
            time.sleep(2)
            resp = httpx.get(f"{VK_API_BASE}/wall.get", params=params, timeout=timeout)
            resp.raise_for_status()
            data = resp.json()
            if "error" not in data:
                rd = data.get("response", {})
                return rd.get("items", []) if isinstance(rd, dict) else rd
        raise RuntimeError(f"VK API error (code={error_code}): {error_msg}")
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
    # VK API requires negative owner_id for groups, positive for users.
    # _resolve_vk_owner_id always returns positive (group ID).
    # Negate it for wall.get.
    wall_owner_id = -owner_id
    all_items: list[dict] = []
    if backfill:
        offset = 0
        for _ in range(100):
            items = _vk_wall_get(wall_owner_id, count=100, offset=offset)
            if not items:
                break
            all_items.extend(items)
            if len(items) < 100:
                break
            offset += 100
    else:
        all_items = _vk_wall_get(wall_owner_id, count=20)

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
    """Fetch recent uploads from a YouTube channel without the YouTube API.

    @handles are resolved through yt-dlp, while channel ids use the public
    uploads RSS feed.
    """
    count = 50 if backfill else 10
    if source_id.strip().lstrip("/").startswith("@"):
        ytdlp_posts = _discover_youtube_via_ytdlp(source_id, count=count)
        if ytdlp_posts:
            return ytdlp_posts

    channel_id = _resolve_youtube_channel_id(source_id)
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(
        "https://www.youtube.com/feeds/videos.xml",
        params={"channel_id": channel_id},
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    resp.raise_for_status()

    result: list[DiscoveredPost] = []
    root = ET.fromstring(resp.text)
    ns = {"atom": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    for entry in root.findall("atom:entry", ns)[:count]:
        video_id = (entry.findtext("yt:videoId", default="", namespaces=ns) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=ns) or "").strip()
        if not video_id:
            continue
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


def _discover_youtube_via_ytdlp(source_id: str, count: int) -> list[DiscoveredPost]:
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return []

    handle = source_id.strip().strip("/")
    url = f"https://www.youtube.com/{handle}"
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _QuietYtdlpLogger(),
        "extract_flat": True,
        "playlistend": count,
        "skip_download": True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception:
        return []

    entries = info.get("entries", []) if isinstance(info, dict) else []
    result: list[DiscoveredPost] = []
    seen: set[str] = set()
    for entry in entries[:count]:
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "").strip()
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        video_url = str(entry.get("url") or "").strip()
        if not video_url.startswith("http"):
            video_url = f"https://www.youtube.com/watch?v={video_id}"
        result.append(DiscoveredPost(external_id=video_id, url=video_url, timestamp=0))
    return result


def _resolve_youtube_channel_id(source_id: str) -> str:
    cleaned = source_id.strip().strip("/")
    if cleaned.startswith("channel/"):
        cleaned = cleaned.split("/", 1)[1]
    if cleaned.startswith("UC") and len(cleaned) >= 20:
        return cleaned

    handle = cleaned if cleaned.startswith("@") else f"@{cleaned}"
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(
        f"https://www.youtube.com/{handle}",
        timeout=timeout,
        follow_redirects=True,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
    )
    resp.raise_for_status()
    html = resp.text

    patterns = [
        r'"channelId":"(UC[A-Za-z0-9_-]+)"',
        r'"browseId":"(UC[A-Za-z0-9_-]+)"',
        r'https://www\.youtube\.com/channel/(UC[A-Za-z0-9_-]+)',
    ]
    for pattern in patterns:
        match = re.search(pattern, html)
        if match:
            return match.group(1)

    raise RuntimeError(f"YouTube channel id not found for: {source_id}")


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
    if result:
        return result
    return _discover_tiktok_via_ytdlp(source_id, count=limit)


def _discover_tiktok_via_ytdlp(source_id: str, count: int) -> list[DiscoveredPost]:
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return []

    username = source_id.strip().lstrip("@")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _QuietYtdlpLogger(),
        "extract_flat": True,
        "playlistend": count,
        "skip_download": True,
    }
    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.tiktok.com/@{username}", download=False)
    except Exception:
        return []

    entries = info.get("entries", []) if isinstance(info, dict) else []
    result: list[DiscoveredPost] = []
    seen: set[str] = set()
    for entry in entries[:count]:
        if not isinstance(entry, dict):
            continue
        video_id = str(entry.get("id") or "").strip()
        if not video_id or video_id in seen:
            continue
        seen.add(video_id)
        video_url = str(entry.get("url") or "").strip()
        if not video_url.startswith("http"):
            video_url = f"https://www.tiktok.com/@{username}/video/{video_id}"
        result.append(DiscoveredPost(external_id=video_id, url=video_url, timestamp=0))
    return result


# ---------------------------------------------------------------------------
# Instagram
# ---------------------------------------------------------------------------

def discover_instagram(source_id: str, backfill: bool = False) -> list[DiscoveredPost]:
    """Scrape Instagram profile for recent post/reel links."""
    limit = 30 if backfill else 12
    session_posts = _discover_instagram_via_session_browser(source_id, count=limit)
    if session_posts:
        return session_posts

    ytdlp_posts = _discover_instagram_via_ytdlp(source_id, count=limit)
    if ytdlp_posts:
        return ytdlp_posts

    url = f"https://www.instagram.com/{source_id}/reels/"
    proxy = get_proxy_for_platform("instagram")
    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    resp = httpx.get(
        url,
        timeout=timeout,
        follow_redirects=True,
        proxy=proxy,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8"},
    )
    resp.raise_for_status()
    html = resp.text

    seen: set[str] = set()
    result: list[DiscoveredPost] = []
    matches = re.findall(r'/(p|reel|reels)/([A-Za-z0-9_-]+)', html)
    if not matches:
        matches = [("reel", sid) for sid in re.findall(r'"shortcode":"([A-Za-z0-9_-]+)"', html)]

    for kind, sid in matches[:limit]:
        if sid in seen:
            continue
        seen.add(sid)
        canonical_kind = "reel" if kind in {"reel", "reels"} else "p"
        result.append(DiscoveredPost(
            external_id=sid,
            url=f"https://www.instagram.com/{canonical_kind}/{sid}/",
            timestamp=0,
        ))
    return result


def _instagram_storage_state_path() -> Path:
    return Path("uploads") / "instagram_storage_state.json"


def _playwright_proxy(proxy: str | None) -> dict | None:
    if not proxy:
        return None
    parsed = urlparse(proxy)
    if not parsed.scheme or not parsed.hostname:
        return {"server": proxy}
    result = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"}
    if parsed.username:
        result["username"] = parsed.username
    if parsed.password:
        result["password"] = parsed.password
    return result


def _discover_instagram_via_session_browser(source_id: str, count: int) -> list[DiscoveredPost]:
    session_path = _instagram_storage_state_path()
    if not session_path.exists():
        return []

    try:
        from playwright.sync_api import sync_playwright
    except Exception:
        return []

    username = source_id.strip().strip("/")
    proxy = _playwright_proxy(get_proxy_for_platform("instagram"))
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context_kwargs = {
                "storage_state": str(session_path),
                "locale": "ru-RU",
                "user_agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
            }
            if proxy:
                context_kwargs["proxy"] = proxy
            context = browser.new_context(**context_kwargs)
            page = context.new_page()
            page.goto(f"https://www.instagram.com/{username}/reels/", wait_until="domcontentloaded", timeout=45_000)
            page.wait_for_timeout(4_000)
            hrefs = page.locator('a[href*="/reel/"], a[href*="/reels/"], a[href*="/p/"]').evaluate_all(
                "(nodes) => nodes.map((node) => node.getAttribute('href')).filter(Boolean)"
            )
            html = page.content()
            context.storage_state(path=str(session_path))
            browser.close()
    except Exception:
        return []

    seen: set[str] = set()
    result: list[DiscoveredPost] = []
    for href in list(hrefs) + re.findall(r"/(reel|reels|p)/([A-Za-z0-9_-]+)", html):
        if isinstance(href, tuple):
            kind, shortcode = href
        else:
            match = re.search(r"/(reel|reels|p)/([A-Za-z0-9_-]+)", str(href))
            if not match:
                continue
            kind, shortcode = match.groups()
        if shortcode in seen:
            continue
        seen.add(shortcode)
        canonical_kind = "reel" if kind in {"reel", "reels"} else "p"
        result.append(DiscoveredPost(
            external_id=shortcode,
            url=f"https://www.instagram.com/{canonical_kind}/{shortcode}/",
            timestamp=0,
        ))
        if len(result) >= count:
            break
    return result


def _discover_instagram_via_ytdlp(source_id: str, count: int) -> list[DiscoveredPost]:
    try:
        from yt_dlp import YoutubeDL
    except Exception:
        return []

    username = source_id.strip().strip("/")
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "logger": _QuietYtdlpLogger(),
        "extract_flat": True,
        "playlistend": count,
        "skip_download": True,
    }
    proxy = get_proxy_for_platform("instagram")
    if proxy:
        ydl_opts["proxy"] = proxy

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"https://www.instagram.com/{username}/reels/", download=False)
    except Exception:
        return []

    entries = info.get("entries", []) if isinstance(info, dict) else []
    result: list[DiscoveredPost] = []
    seen: set[str] = set()
    for entry in entries[:count]:
        if not isinstance(entry, dict):
            continue
        shortcode = str(entry.get("id") or entry.get("display_id") or "").strip()
        video_url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
        match = re.search(r"/(p|reel|reels)/([A-Za-z0-9_-]+)", video_url)
        if match:
            kind, shortcode = match.groups()
        else:
            kind = "reel"
        if not shortcode or shortcode in seen:
            continue
        seen.add(shortcode)
        canonical_kind = "reel" if kind in {"reel", "reels"} else "p"
        result.append(DiscoveredPost(
            external_id=shortcode,
            url=f"https://www.instagram.com/{canonical_kind}/{shortcode}/",
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
