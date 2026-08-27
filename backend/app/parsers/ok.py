import asyncio
import re
from urllib.parse import urlparse

import httpx

from app.parsers._jsonld import extract_interaction_counts
from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.parsers.ytdlp_common import fetch_via_ytdlp
from app.services.hashtag_extractor import extract_hashtags
from app.services.proxy_routing import get_proxy_for_platform

_OK_VIDEO_PATH = re.compile(r"/(?:video|live|videoembed|web-api/video/moviePlayer)/")


def _parse_compact_count(value: str | None) -> int:
    """Parse compact count like '2.8K', '1,5 млн', '500 тыс'."""
    if not value:
        return 0

    normalized = value.strip().lower().replace("\xa0", " ").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return 0

    number = float(match.group(1))
    if any(unit in normalized for unit in ("млрд", "b", "bn")):
        number *= 1_000_000_000
    elif any(unit in normalized for unit in ("млн", "m", "million")):
        number *= 1_000_000
    elif any(unit in normalized for unit in ("тыс", "k")):
        number *= 1_000
    return int(number)


def _fetch_video_playwright_sync(url: str) -> Metrics:
    """Fetch OK video metrics via headless Chromium."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ParserUnavailableError("Playwright is not installed") from exc

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            locale="ru-RU",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/135.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        try:
            response = page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            if response is not None and response.status == 404:
                raise ParserNotFoundError(f"OK_CONTENT_NOT_FOUND: OK video not found: {url}")

            try:
                page.wait_for_selector(".vp-layer-info_cnt, .widget_count", timeout=10_000)
            except Exception as exc:
                title_lower = page.title().lower()
                body_text = ""
                try:
                    body_text = page.locator("body").inner_text(timeout=3_000).lower()
                except Exception:
                    pass
                if "не найден" in title_lower or "not found" in title_lower:
                    raise ParserNotFoundError(f"OK_CONTENT_NOT_FOUND: OK video not found: {url}") from exc
                if "видео заблокировано" in body_text or "video is blocked" in body_text:
                    raise ParserNotFoundError(f"OK_CONTENT_BLOCKED: OK video is blocked: {url}") from exc
                raise ParserUnavailableError(
                    f"OK_NO_VIDEO_PLAYER: OK page did not render video player: {url}"
                ) from exc

            try:
                page.wait_for_selector(".comments-counter", timeout=5_000)
            except Exception:
                pass

            views = 0
            info_el = page.locator(".vp-layer-info_cnt").first
            if info_el.count():
                info_text = info_el.inner_text()
                views_match = re.search(
                    r"([\d.,]+\s*(?:тыс|млн|млрд|[KkMmBb])?)\s*(?:просмотр|views?)",
                    info_text,
                    re.I,
                )
                if views_match:
                    views = _parse_compact_count(views_match.group(1))

            likes = 0
            reposts = 0
            comments = 0

            widget_counters = page.locator(".widget_count.js-count").all()
            if len(widget_counters) >= 1:
                likes = _parse_compact_count(widget_counters[0].inner_text())
            if len(widget_counters) >= 2:
                reposts = _parse_compact_count(widget_counters[1].inner_text())

            comments_el = page.locator(".comments-counter").first
            if comments_el.count():
                comments = _parse_compact_count(comments_el.inner_text())

            hashtags: list[str] = []
            title_el = page.locator(".vp-layer-info_title, .video-card_title, [class*='video-info'] h1, h1").first
            if title_el.count():
                hashtags.extend(extract_hashtags(title_el.inner_text()))
            desc_el = page.locator(".vp-layer-info_desc, .video-card_desc, [class*='video-info'] [class*='desc']").first
            if desc_el.count():
                for hashtag in extract_hashtags(desc_el.inner_text()):
                    if hashtag not in hashtags:
                        hashtags.append(hashtag)
        finally:
            browser.close()

    return Metrics(
        likes=likes,
        reposts=reposts,
        comments=comments,
        saves=0,
        views=views,
        hashtags=hashtags,
    )


_OK_BROWSER_TIMEOUT = 45


async def _fetch_video_via_browser(url: str) -> Metrics:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_video_playwright_sync, url),
            timeout=_OK_BROWSER_TIMEOUT,
        )
    except asyncio.TimeoutError as exc:
        raise ParserUnavailableError(f"OK browser fetch timed out ({_OK_BROWSER_TIMEOUT}s): {url}") from exc


async def fetch(url: str) -> Metrics:
    """Fetch OK.ru metrics."""
    parsed_path = urlparse(url).path or ""

    if _OK_VIDEO_PATH.search(parsed_path):
        try:
            return await _fetch_video_via_browser(url)
        except ParserNotFoundError:
            raise
        except ParserUnavailableError:
            pass

        try:
            return await fetch_via_ytdlp(url)
        except ParserNotFoundError as exc:
            raise ParserNotFoundError(f"OK video not found: {url}") from exc
        except ParserUnavailableError as exc:
            raise ParserUnavailableError(f"OK video unavailable: {url}") from exc

    return await _fetch_topic_post(url)


async def _fetch_topic_post(url: str) -> Metrics:
    proxy = get_proxy_for_platform("ok")
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, proxy=proxy) as client:
        response = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})

    if response.status_code == 404:
        raise ParserNotFoundError(f"OK_CONTENT_NOT_FOUND: OK post not found: {url}")
    if response.status_code != 200:
        raise ParserUnavailableError(f"OK_HTTP_ERROR: OK returned status {response.status_code}")

    counts = extract_interaction_counts(response.text)
    if counts:
        return Metrics(
            likes=counts.get("likes", 0),
            reposts=counts.get("reposts", 0),
            comments=counts.get("comments", 0),
            saves=0,
            views=counts.get("views", 0),
        )

    raise ParserUnavailableError(
        f"OK_METRICS_UNAVAILABLE: Could not extract public metrics from OK topic page: {url}"
    )
