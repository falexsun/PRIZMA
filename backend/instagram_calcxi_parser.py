#!/usr/bin/env python3
"""
Instagram Reel metrics through a buffer website (Calcxi).

Idea:
    Reel URL -> Calcxi -> Calcxi fetches Instagram -> we read Calcxi result

No Instagram login, sessionid, Meta token, Apify token, or RapidAPI key.

Install:
    pip install playwright
    playwright install chromium

Run:
    python instagram_calcxi_parser.py "https://www.instagram.com/reel/SHORTCODE/"

Optional:
    python instagram_calcxi_parser.py URL --headed
    python instagram_calcxi_parser.py URL --debug
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, Response


CALCXI_URL = "https://calcxi.com/instagram-reels-downloader/"


class BufferSiteError(RuntimeError):
    pass


@dataclass
class ReelStats:
    reel_url: str
    source: str = "calcxi"
    likes: int | None = None
    views: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    reposts: int | None = None
    duration_seconds: float | None = None
    caption: str | None = None
    creator: str | None = None
    video_url: str | None = None
    thumbnail_url: str | None = None
    extraction_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_reel_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host not in {"instagram.com", "www.instagram.com"}:
        raise ValueError("Нужна ссылка instagram.com")
    if not re.search(r"/(reels?|p|tv)/[A-Za-z0-9_-]+", parsed.path):
        raise ValueError("Нужна ссылка вида https://www.instagram.com/reel/SHORTCODE/ или /p/SHORTCODE/")


def to_number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)

    s = str(value).strip().replace("\u00a0", "").replace(" ", "").replace(",", "")
    if not s or s in {"—", "-", "null", "None", "N/A"}:
        return None

    m = re.fullmatch(r"([\d.]+)([KMB])?", s, flags=re.I)
    if not m:
        # Sometimes text is "12,345 likes"
        m = re.search(r"([\d.,]+)\s*([KMB])?", str(value), flags=re.I)
        if not m:
            return None
        n_str = m.group(1).replace(",", "")
        suffix = (m.group(2) or "").upper()
    else:
        n_str = m.group(1)
        suffix = (m.group(2) or "").upper()

    try:
        n = float(n_str)
    except ValueError:
        return None

    mult = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
    return int(n * mult)


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


ALIASES = {
    "likes": (
        "likes", "like_count", "likeCount", "likesCount",
    ),
    "views": (
        "views", "view_count", "viewCount", "viewsCount",
        "play_count", "playCount", "videoPlayCount", "video_view_count",
    ),
    "comments": (
        "comments", "comment_count", "commentCount", "commentsCount",
    ),
    "shares": (
        "shares", "share_count", "shareCount", "sharesCount", "reshareCount",
    ),
    "saves": (
        "saves", "save_count", "saveCount", "savesCount", "saved_count", "collectCount",
    ),
    "reposts": (
        "reposts", "repost_count", "repostCount",
    ),
}

URL_ALIASES = {
    "video_url": ("video_url", "videoUrl", "download_url", "downloadUrl", "media_url"),
    "thumbnail_url": ("thumbnail_url", "thumbnailUrl", "display_url", "displayUrl"),
}
TEXT_ALIASES = {
    "caption": ("caption", "description", "text"),
    "creator": ("creator", "username", "ownerUsername", "author"),
}
DURATION_ALIASES = ("duration", "duration_seconds", "videoDuration", "video_duration")


def _first_present(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for k in keys:
        if k in d and d[k] not in (None, "", "—"):
            return d[k]
    return None


def stats_from_json(payload: Any, reel_url: str) -> ReelStats | None:
    """
    Search any JSON returned by the buffer site.
    This intentionally supports many possible field names so it survives
    backend changes and can also work with similar viewer sites.
    """
    best: ReelStats | None = None
    best_score = 0

    for d in _walk(payload):
        stats = ReelStats(reel_url=reel_url, extraction_source="network-json")
        score = 0

        for field, aliases in ALIASES.items():
            raw = _first_present(d, aliases)
            value = to_number(raw)
            if value is not None:
                setattr(stats, field, value)
                score += 4

        for field, aliases in URL_ALIASES.items():
            raw = _first_present(d, aliases)
            if isinstance(raw, str) and raw.startswith("http"):
                setattr(stats, field, raw)
                score += 1

        for field, aliases in TEXT_ALIASES.items():
            raw = _first_present(d, aliases)
            if isinstance(raw, str) and raw.strip():
                setattr(stats, field, raw.strip())
                score += 1

        raw_duration = _first_present(d, DURATION_ALIASES)
        if raw_duration is not None:
            try:
                stats.duration_seconds = float(raw_duration)
                score += 1
            except (TypeError, ValueError):
                pass

        # Avoid choosing random analytics objects from unrelated scripts.
        if stats.likes is not None:
            score += 2
        if stats.views is not None:
            score += 3
        if stats.video_url:
            score += 2

        if score > best_score:
            best = stats
            best_score = score

    return best if best_score >= 4 else None


def stats_from_text(text: str, reel_url: str) -> ReelStats | None:
    """
    DOM fallback. Calcxi currently renders:
        Reel Stats
        Likes
        ...
        Views
        ...
        Duration
        ...
    """
    stats = ReelStats(reel_url=reel_url, extraction_source="dom-text")

    patterns = {
        "likes": [
            r"(?:❤️\s*)?Likes\s*[:\n]\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+likes\b",
        ],
        "views": [
            r"(?:👁\s*)?Views\s*[:\n]\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+views\b",
        ],
        "comments": [
            r"Comments\s*[:\n]\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+comments\b",
        ],
        "shares": [
            r"Shares\s*[:\n]\s*([\d.,]+\s*[KMB]?)",
        ],
        "saves": [
            r"Saves\s*[:\n]\s*([\d.,]+\s*[KMB]?)",
        ],
        "reposts": [
            r"Reposts\s*[:\n]\s*([\d.,]+\s*[KMB]?)",
        ],
    }

    found = 0
    for field, pats in patterns.items():
        for pat in pats:
            m = re.search(pat, text, flags=re.I)
            if m:
                value = to_number(m.group(1))
                if value is not None:
                    setattr(stats, field, value)
                    found += 1
                    break

    dm = re.search(
        r"Duration\s*[:\n]\s*(?:(\d+):)?(\d{1,2})(?::(\d{1,2}))?\b",
        text,
        flags=re.I,
    )
    if dm:
        a, b, c = dm.groups()
        if c is not None:
            stats.duration_seconds = int(a or 0) * 3600 + int(b) * 60 + int(c)
        else:
            stats.duration_seconds = int(a or 0) * 60 + int(b)

    # Caption fallback: deliberately conservative.
    cm = re.search(
        r"Caption\s*\n(.+?)(?=\n\s*Reel Stats|\n\s*📊|\Z)",
        text,
        flags=re.I | re.S,
    )
    if cm:
        caption = cm.group(1).strip()
        if caption and len(caption) < 5000:
            stats.caption = caption

    return stats if found > 0 else None


def merge_stats(primary: ReelStats | None, secondary: ReelStats | None, reel_url: str) -> ReelStats:
    if not primary and not secondary:
        raise BufferSiteError("Calcxi не вернул распознаваемые метрики")

    out = primary or secondary or ReelStats(reel_url=reel_url)
    if secondary and secondary is not out:
        for field in (
            "likes", "views", "comments", "shares", "saves", "reposts",
            "duration_seconds", "caption", "creator", "video_url", "thumbnail_url"
        ):
            if getattr(out, field) is None:
                setattr(out, field, getattr(secondary, field))

    return out


async def _find_input(page: Page):
    selectors = [
        'input[type="url"]',
        'input[placeholder*="instagram" i]',
        'input[placeholder*="reel" i]',
        'input[type="text"]',
    ]
    for selector in selectors:
        loc = page.locator(selector)
        count = await loc.count()
        for i in range(count):
            candidate = loc.nth(i)
            if await candidate.is_visible():
                return candidate
    raise BufferSiteError("Не нашёл поле для Instagram URL на Calcxi")


async def _find_submit(page: Page):
    # Prefer exact-ish button labels.
    candidates = [
        page.get_by_role("button", name=re.compile(r"download\s*reel", re.I)),
        page.get_by_role("button", name=re.compile(r"download", re.I)),
        page.locator('button[type="submit"]'),
    ]

    for loc in candidates:
        count = await loc.count()
        for i in range(count):
            btn = loc.nth(i)
            if await btn.is_visible():
                return btn
    raise BufferSiteError("Не нашёл кнопку запуска на Calcxi")


async def scrape_calcxi(
    reel_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
    debug: bool = False,
) -> ReelStats:
    validate_reel_url(reel_url)

    captured_json: list[Any] = []
    interesting_urls: list[str] = []

    async with async_playwright() as p:
        launch_kwargs = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }

        # Useful on servers/containers where Playwright package exists but its
        # bundled browser was not downloaded.
        import os
        if os.path.exists("/usr/bin/chromium"):
            launch_kwargs["executable_path"] = "/usr/bin/chromium"

        browser = await p.chromium.launch(**launch_kwargs)

        context = await browser.new_context(
            viewport={"width": 1365, "height": 900},
            locale="en-US",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
        )
        page = await context.new_page()

        async def on_response(response: Response):
            url_l = response.url.lower()
            ctype = (await response.all_headers()).get("content-type", "").lower()

            # Save possible backend endpoints for debugging/reverse engineering.
            if any(x in url_l for x in ("api", "ajax", "reel", "instagram", "download")):
                interesting_urls.append(response.url)

            if "json" in ctype:
                try:
                    captured_json.append(await response.json())
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            await page.goto(CALCXI_URL, wait_until="domcontentloaded", timeout=timeout_ms)

            input_box = await _find_input(page)
            await input_box.fill(reel_url)

            button = await _find_submit(page)
            await button.click()

            # Calcxi currently tells users fetching normally takes several seconds.
            # Poll for either numeric DOM stats or a useful JSON response.
            deadline = asyncio.get_running_loop().time() + timeout_ms / 1000

            best_json = None
            best_dom = None

            while asyncio.get_running_loop().time() < deadline:
                for payload in reversed(captured_json):
                    candidate = stats_from_json(payload, reel_url)
                    if candidate and (
                        candidate.views is not None
                        or candidate.likes is not None
                    ):
                        best_json = candidate
                        break

                body_text = await page.locator("body").inner_text()
                best_dom = stats_from_text(body_text, reel_url)

                # One real engagement metric is enough to stop, but wait a bit if
                # only likes arrived and views might still render.
                complete_enough = (
                    (best_json and best_json.views is not None and best_json.likes is not None)
                    or
                    (best_dom and best_dom.views is not None and best_dom.likes is not None)
                )
                if complete_enough:
                    break

                await page.wait_for_timeout(750)

            if debug:
                print(
                    json.dumps(
                        {
                            "interesting_network_urls": list(dict.fromkeys(interesting_urls)),
                            "captured_json_responses": len(captured_json),
                            "page_url": page.url,
                        },
                        ensure_ascii=False,
                        indent=2,
                    ),
                    file=sys.stderr,
                )

            # Prefer network data because it is usually exact; fill gaps from DOM.
            result = merge_stats(best_json, best_dom, reel_url)

            if all(
                getattr(result, f) is None
                for f in ("views", "likes", "comments", "shares", "saves", "reposts")
            ):
                raise BufferSiteError("Calcxi загрузился, но не показал engagement metrics")

            return result

        finally:
            await context.close()
            await browser.close()


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Получить публичные Instagram Reel metrics через Calcxi"
    )
    parser.add_argument("url", help="Instagram Reel URL")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Запустить видимый Chromium (полезно при антибот-защите)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Показать найденные network endpoints в stderr",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout в секундах (default: 60)",
    )
    args = parser.parse_args()

    try:
        result = await scrape_calcxi(
            args.url,
            headless=not args.headed,
            timeout_ms=args.timeout * 1000,
            debug=args.debug,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
