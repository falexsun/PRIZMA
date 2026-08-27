#!/usr/bin/env python3
"""
TikTok metrics parser through TT-View:
    https://tt-view.com/tiktok-video-viewer

TT-View accepts a public TikTok video URL and displays visible public metrics:
views, likes, comments, shares, saves.

This script does NOT require:
- TikTok login
- TikTok cookies/session
- TikTok API key
- Apify/RapidAPI token

Install:
    pip install playwright
    playwright install chromium

Usage:
    python tiktok_ttview_parser.py \
      "https://www.tiktok.com/@nba/video/1234567890123456789"

Debug network requests:
    python tiktok_ttview_parser.py URL --debug

Visible browser:
    python tiktok_ttview_parser.py URL --headed
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


TTVIEW_URL = "https://tt-view.com/tiktok-video-viewer"


class TTViewError(RuntimeError):
    pass


@dataclass
class TikTokStats:
    video_url: str
    source: str = "tt-view"
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    author: str | None = None
    caption: str | None = None
    duration_seconds: float | None = None
    created_at: str | None = None
    cover_url: str | None = None
    extraction_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_tiktok_url(url: str) -> None:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    valid_host = (
        host == "tiktok.com"
        or host.endswith(".tiktok.com")
    )

    if not valid_host:
        raise ValueError("Нужна ссылка на TikTok")

    # Direct videos normally contain /video/, while vm/vt links are redirects.
    if host not in {"vm.tiktok.com", "vt.tiktok.com"} and "/video/" not in parsed.path:
        raise ValueError(
            "Нужна ссылка на конкретное TikTok-видео, например "
            "https://www.tiktok.com/@user/video/123..."
        )


def to_number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return int(value)

    s = str(value).strip()

    if not s or s.lower() in {"n/a", "none", "null", "-", "—"}:
        return None

    # Supports:
    # 12,345
    # 12.3K
    # 1.2M
    # 4B
    m = re.search(r"([\d.,]+)\s*([KMB])?", s, flags=re.I)
    if not m:
        return None

    raw = m.group(1)
    suffix = (m.group(2) or "").upper()

    if suffix:
        # "12.5K"
        raw = raw.replace(",", "")
        try:
            value_num = float(raw)
        except ValueError:
            return None
    else:
        # For plain counters assume separators, not decimals.
        raw = raw.replace(",", "").replace(".", "")
        try:
            value_num = float(raw)
        except ValueError:
            return None

    multiplier = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }[suffix]

    return int(value_num * multiplier)


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


METRIC_ALIASES = {
    "views": (
        "views",
        "view_count",
        "viewCount",
        "viewsCount",
        "play_count",
        "playCount",
        "play_count_text",
    ),
    "likes": (
        "likes",
        "like_count",
        "likeCount",
        "likesCount",
        "digg_count",
        "diggCount",
    ),
    "comments": (
        "comments",
        "comment_count",
        "commentCount",
        "commentsCount",
    ),
    "shares": (
        "shares",
        "share_count",
        "shareCount",
        "sharesCount",
    ),
    "saves": (
        "saves",
        "save_count",
        "saveCount",
        "savesCount",
        "collect_count",
        "collectCount",
        "favorite_count",
        "favoriteCount",
    ),
}

TEXT_ALIASES = {
    "author": (
        "author",
        "username",
        "uniqueId",
        "unique_id",
        "nickname",
    ),
    "caption": (
        "caption",
        "description",
        "desc",
        "text",
    ),
    "created_at": (
        "created_at",
        "createdAt",
        "createTimeISO",
        "create_time",
    ),
}

DURATION_ALIASES = (
    "duration",
    "duration_seconds",
    "durationSeconds",
    "video_duration",
)

COVER_ALIASES = (
    "cover_url",
    "coverUrl",
    "cover",
    "thumbnail",
    "thumbnail_url",
    "thumbnailUrl",
)


def _first(d: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in d and d[key] not in (None, "", "-", "—"):
            return d[key]
    return None


def stats_from_json(payload: Any, input_url: str) -> TikTokStats | None:
    """
    Finds the most likely video object in any XHR/fetch JSON returned by TT-View.
    The code deliberately supports TikTok-native and normalized field names.
    """
    best: TikTokStats | None = None
    best_score = 0

    for item in _walk(payload):
        candidate = TikTokStats(
            video_url=input_url,
            extraction_source="network-json",
        )
        score = 0

        for field, aliases in METRIC_ALIASES.items():
            value = to_number(_first(item, aliases))
            if value is not None:
                setattr(candidate, field, value)
                score += 4

        for field, aliases in TEXT_ALIASES.items():
            value = _first(item, aliases)
            if isinstance(value, str) and value.strip():
                setattr(candidate, field, value.strip())
                score += 1

        duration = _first(item, DURATION_ALIASES)
        if duration is not None:
            try:
                candidate.duration_seconds = float(duration)
                score += 1
            except (TypeError, ValueError):
                pass

        cover = _first(item, COVER_ALIASES)
        if isinstance(cover, str) and cover.startswith("http"):
            candidate.cover_url = cover
            score += 1

        # Stronger confidence when TT-View gives multiple engagement counters.
        visible_metrics = sum(
            getattr(candidate, key) is not None
            for key in ("views", "likes", "comments", "shares", "saves")
        )
        score += visible_metrics * 2

        if candidate.views is not None:
            score += 2

        if score > best_score:
            best = candidate
            best_score = score

    return best if best_score >= 6 else None


def stats_from_text(text: str, input_url: str) -> TikTokStats | None:
    """
    DOM fallback.

    TT-View documents these result counters:
      Views, Likes, Comments, Shares, Saves

    Handles layouts like:
      Views
      1.2M

    and:
      Views: 1.2M
    """
    result = TikTokStats(
        video_url=input_url,
        extraction_source="dom-text",
    )

    patterns = {
        "views": (
            r"\bViews?\b\s*[:\n\r\t ]+\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+\bViews?\b",
        ),
        "likes": (
            r"\bLikes?\b\s*[:\n\r\t ]+\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+\bLikes?\b",
        ),
        "comments": (
            r"\bComments?\b\s*[:\n\r\t ]+\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+\bComments?\b",
        ),
        "shares": (
            r"\bShares?\b\s*[:\n\r\t ]+\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+\bShares?\b",
        ),
        "saves": (
            r"\bSaves?\b\s*[:\n\r\t ]+\s*([\d.,]+\s*[KMB]?)",
            r"([\d.,]+\s*[KMB]?)\s+\bSaves?\b",
        ),
    }

    found = 0

    for field, field_patterns in patterns.items():
        for pattern in field_patterns:
            m = re.search(pattern, text, flags=re.I)
            if not m:
                continue

            value = to_number(m.group(1))
            if value is not None:
                setattr(result, field, value)
                found += 1
                break

    # Optional fields.
    m = re.search(
        r"\bDuration\b\s*[:\n\r\t ]+\s*(\d+(?:\.\d+)?)\s*(?:s|sec|seconds?)?\b",
        text,
        flags=re.I,
    )
    if m:
        result.duration_seconds = float(m.group(1))

    return result if found else None


def merge_stats(
    network: TikTokStats | None,
    dom: TikTokStats | None,
    input_url: str,
) -> TikTokStats:
    if network is None and dom is None:
        raise TTViewError("TT-View не вернул распознаваемые метрики")

    result = network or dom or TikTokStats(video_url=input_url)

    if network and dom:
        for field in (
            "views",
            "likes",
            "comments",
            "shares",
            "saves",
            "author",
            "caption",
            "duration_seconds",
            "created_at",
            "cover_url",
        ):
            if getattr(result, field) is None:
                setattr(result, field, getattr(dom, field))

    return result


async def find_url_input(page: Page):
    selectors = [
        'input[type="url"]',
        'input[placeholder*="tiktok" i]',
        'input[placeholder*="https://" i]',
        'input[type="text"]',
    ]

    for selector in selectors:
        locator = page.locator(selector)
        for i in range(await locator.count()):
            item = locator.nth(i)
            if await item.is_visible():
                return item

    raise TTViewError("Не удалось найти поле TikTok URL на TT-View")


async def find_submit_button(page: Page):
    candidates = [
        page.get_by_role(
            "button",
            name=re.compile(r"view\s+video\s+details", re.I),
        ),
        page.get_by_role(
            "button",
            name=re.compile(r"video\s+details", re.I),
        ),
        page.locator('button[type="submit"]'),
        page.get_by_role(
            "button",
            name=re.compile(r"view|check|lookup|submit", re.I),
        ),
    ]

    for locator in candidates:
        for i in range(await locator.count()):
            button = locator.nth(i)
            if await button.is_visible():
                return button

    raise TTViewError("Не удалось найти кнопку View video details")


async def scrape_ttview(
    video_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
    debug: bool = False,
    proxy_server: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
) -> TikTokStats:
    validate_tiktok_url(video_url)

    captured_json: list[Any] = []
    interesting_requests: list[dict[str, Any]] = []

    async with async_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }

        import os
        if os.path.exists("/usr/bin/chromium"):
            launch_kwargs["executable_path"] = "/usr/bin/chromium"

        browser = await p.chromium.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {
            "locale": "en-US",
            "viewport": {"width": 1365, "height": 900},
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "extra_http_headers": {
                "Accept-Language": "en-US,en;q=0.9",
            },
        }
        if proxy_server:
            proxy_cfg: dict[str, Any] = {"server": proxy_server}
            if proxy_username:
                proxy_cfg["username"] = proxy_username
            if proxy_password:
                proxy_cfg["password"] = proxy_password
            context_kwargs["proxy"] = proxy_cfg

        context = await browser.new_context(**context_kwargs)

        page = await context.new_page()

        async def on_response(response: Response):
            url = response.url
            url_lower = url.lower()

            # Keep possible backend URLs. This is useful to later replace
            # Playwright with a direct requests/httpx call.
            if any(
                token in url_lower
                for token in (
                    "/api/",
                    "video",
                    "tiktok",
                    "lookup",
                    "viewer",
                    "details",
                )
            ):
                interesting_requests.append(
                    {
                        "status": response.status,
                        "url": url,
                    }
                )

            content_type = (
                (await response.all_headers())
                .get("content-type", "")
                .lower()
            )

            if "json" in content_type:
                try:
                    captured_json.append(await response.json())
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            await page.goto(
                TTVIEW_URL,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            input_box = await find_url_input(page)
            await input_box.fill(video_url)

            submit = await find_submit_button(page)
            await submit.click()

            deadline = (
                asyncio.get_running_loop().time()
                + timeout_ms / 1000
            )

            network_result: TikTokStats | None = None
            dom_result: TikTokStats | None = None

            while asyncio.get_running_loop().time() < deadline:
                # Search new JSON responses first.
                for payload in reversed(captured_json):
                    candidate = stats_from_json(payload, video_url)

                    if candidate is not None:
                        network_result = candidate

                        if all(
                            getattr(candidate, field) is not None
                            for field in (
                                "views",
                                "likes",
                                "comments",
                                "shares",
                                "saves",
                            )
                        ):
                            break

                body_text = await page.locator("body").inner_text()
                dom_result = stats_from_text(body_text, video_url)

                best = network_result or dom_result

                # TikTok public counters are the whole point here.
                if best:
                    available = sum(
                        getattr(best, field) is not None
                        for field in (
                            "views",
                            "likes",
                            "comments",
                            "shares",
                            "saves",
                        )
                    )

                    # Wait for the complete result if possible.
                    if available >= 5:
                        break

                    # Four metrics is already useful; give the final metric
                    # a little more time to render.
                    if available >= 4:
                        await page.wait_for_timeout(1500)

                        body_text = await page.locator("body").inner_text()
                        dom_result = stats_from_text(body_text, video_url)
                        break

                await page.wait_for_timeout(750)

            if debug:
                debug_result = {
                    "ttview_page": page.url,
                    "captured_json_responses": len(captured_json),
                    "interesting_requests": list(
                        {
                            (x["status"], x["url"]): x
                            for x in interesting_requests
                        }.values()
                    ),
                }

                print(
                    json.dumps(
                        debug_result,
                        ensure_ascii=False,
                        indent=2,
                    ),
                    file=sys.stderr,
                )

            result = merge_stats(
                network_result,
                dom_result,
                video_url,
            )

            if all(
                getattr(result, field) is None
                for field in (
                    "views",
                    "likes",
                    "comments",
                    "shares",
                    "saves",
                )
            ):
                raise TTViewError(
                    "TT-View открылся, но engagement counters не найдены"
                )

            return result

        finally:
            await context.close()
            await browser.close()


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse TikTok video stats through TT-View"
    )

    parser.add_argument(
        "url",
        help="Public TikTok video URL",
    )

    parser.add_argument(
        "--headed",
        action="store_true",
        help="Запустить видимый Chromium",
    )

    parser.add_argument(
        "--debug",
        action="store_true",
        help="Показать XHR/fetch URLs TT-View в stderr",
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout в секундах, default=60",
    )

    args = parser.parse_args()

    try:
        result = await scrape_ttview(
            args.url,
            headless=not args.headed,
            timeout_ms=args.timeout * 1000,
            debug=args.debug,
        )
    except Exception as exc:
        print(
            f"ERROR: {exc}",
            file=sys.stderr,
        )
        return 1

    print(
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
