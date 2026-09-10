import asyncio
import re
from urllib.parse import urlparse

import httpx

from app.parsers._jsonld import extract_interaction_counts
from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.parsers.ytdlp_common import fetch_via_ytdlp
from app.services.hashtag_extractor import extract_hashtags
from app.services.proxy_routing import get_proxy_for_platform

_OK_VIDEO_PATH = re.compile(r"/(?:video|clip|live|videoembed|web-api/video/moviePlayer)/")


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
        # Video/clip: try browser first, then yt-dlp fallback
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

    # Topic/post: try HTML scraping first, fall back to browser
    return await _fetch_topic_post(url)


def _parse_ok_reaction_text(text: str) -> tuple[int, int]:
    """Parse OK reaction text like '3 классаПоделились: 1' into (likes, shares)."""
    likes_match = re.search(r"(\d+)\s*класс", text)
    shares_match = re.search(r"Поделились:\s*(\d+)", text)
    likes = int(likes_match.group(1)) if likes_match else 0
    shares = int(shares_match.group(1)) if shares_match else 0
    return likes, shares


def _extract_group_feed_url(url: str) -> str | None:
    """Extract the group feed URL from a topic URL."""
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    # /group/60690308923443/topic/... -> /group/60690308923443
    m = re.match(r"(group/\d+)", path)
    if m:
        return f"https://ok.ru/{m.group(1)}"
    # /screenname/topic/... -> /screenname
    parts = path.split("/")
    if len(parts) >= 2 and parts[1] == "topic":
        return f"https://ok.ru/{parts[0]}"
    return None


def _extract_topic_id(url: str) -> str | None:
    """Extract topic ID from a topic URL."""
    m = re.search(r"/topic/(\d+)", url)
    return m.group(1) if m else None


def _parse_ok_group_feed(html: str) -> dict[str, tuple[int, int]]:
    """Parse OK group feed page for topic metrics. Returns {topic_id: (likes, shares)}."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, tuple[int, int]] = {}

    for el in soup.find_all(attrs={"data-l": True}):
        dl = el.get("data-l", "")
        if "extendedReactionsFeedback" not in dl:
            continue

        text = el.get_text(strip=True)
        likes, shares = _parse_ok_reaction_text(text)

        # Find the topic URL in parent elements
        parent = el.parent
        for _ in range(8):
            if parent is None:
                break
            links = parent.find_all("a", href=re.compile(r"/topic/\d+"))
            for link in links:
                href = link.get("href", "")
                tid = re.search(r"/topic/(\d+)", href)
                if tid:
                    topic_id = tid.group(1)
                    if topic_id not in result or (likes + shares) > sum(result[topic_id]):
                        result[topic_id] = (likes, shares)
                    break
            if links:
                break
            parent = parent.parent

    return result


def _fetch_topic_via_feed_pagination_sync(feed_url: str, topic_id: str, max_clicks: int = 20) -> tuple[int, int]:
    """Paginate OK group feed via Playwright to find an old topic. Returns (likes, shares)."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="ru-RU",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/135.0.0.0 Safari/537.36",
        )
        page = ctx.new_page()
        try:
            page.goto(feed_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(3000)

            for _ in range(max_clicks):
                # Check if topic is on the page
                topic_link = page.locator(f'a[href*="/topic/{topic_id}"]').first
                if topic_link.count():
                    # Walk up to find the reaction feedback element
                    parent = topic_link
                    for _ in range(15):
                        parent = parent.locator("..").first
                        reaction_el = parent.locator('[data-l*="extendedReactionsFeedback"]').first
                        if reaction_el.count():
                            text = reaction_el.inner_text()
                            return _parse_ok_reaction_text(text)
                    return (0, 0)

                # Scroll down and click "Показать еще"
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(1500)
                clicked = page.evaluate("""
                    () => {
                        const btns = document.querySelectorAll('.js-show-more');
                        for (const btn of btns) { btn.click(); return true; }
                        return false;
                    }
                """)
                if not clicked:
                    break
                page.wait_for_timeout(2500)
        finally:
            browser.close()

    return (0, 0)


async def _fetch_topic_post(url: str) -> Metrics:
    """Fetch OK topic metrics: fast HTTP feed first, then Playwright pagination for old posts."""
    proxy = get_proxy_for_platform("ok")
    topic_id = _extract_topic_id(url)
    feed_url = _extract_group_feed_url(url)

    if not feed_url or not topic_id:
        raise ParserUnavailableError(f"Cannot extract group/topic from URL: {url}")

    # Fast path: scrape first page of group feed via HTTP
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True, proxy=proxy) as client:
            response = await client.get(feed_url, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 200:
            feed_metrics = _parse_ok_group_feed(response.text)
            if topic_id in feed_metrics:
                likes, shares = feed_metrics[topic_id]
                return Metrics(likes=likes, reposts=shares, comments=0, saves=0, views=0)
    except Exception:
        pass

    # Slow path: paginate the feed with Playwright to find old posts
    try:
        likes, shares = await asyncio.wait_for(
            asyncio.to_thread(_fetch_topic_via_feed_pagination_sync, feed_url, topic_id),
            timeout=120,
        )
        if likes > 0 or shares > 0:
            return Metrics(likes=likes, reposts=shares, comments=0, saves=0, views=0)
    except asyncio.TimeoutError:
        pass
    except Exception:
        pass

    # Fallback: JSON-LD on the topic page itself (only commentCount available)
    try:
        async with httpx.AsyncClient(timeout=10, follow_redirects=True, proxy=proxy) as client:
            resp = await client.get(url, headers={"User-Agent": "Mozilla/5.0"})
        if resp.status_code == 404:
            raise ParserNotFoundError(f"OK topic not found: {url}")
        counts = extract_interaction_counts(resp.text)
        return Metrics(likes=0, reposts=0, comments=counts.get("comments", 0), saves=0, views=0)
    except ParserNotFoundError:
        raise
    except Exception as exc:
        raise ParserUnavailableError(f"OK topic fetch failed: {url}: {exc}") from exc


def _ok_page_playwright_sync(url: str) -> Metrics:
    """Generic OK page metrics via headless Chromium (topics, clips, etc.)."""
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
                raise ParserNotFoundError(f"OK_CONTENT_NOT_FOUND: {url}")

            # Wait for page to render
            try:
                page.wait_for_selector(
                    ".widget_count, .comments-counter, .vp-layer-info_cnt, .feed_ct, [data-l]",
                    timeout=10_000,
                )
            except Exception:
                pass

            # Check for error pages
            title_lower = page.title().lower()
            if "не найден" in title_lower or "not found" in title_lower:
                raise ParserNotFoundError(f"OK_CONTENT_NOT_FOUND: {url}")

            likes = 0
            reposts = 0
            comments = 0
            views = 0

            # Method 1: widget_count elements (like/share/comment buttons)
            widget_counters = page.locator(".widget_count.js-count").all()
            if len(widget_counters) >= 1:
                likes = _parse_compact_count(widget_counters[0].inner_text())
            if len(widget_counters) >= 2:
                reposts = _parse_compact_count(widget_counters[1].inner_text())

            # Method 2: comments counter
            comments_el = page.locator(".comments-counter").first
            if comments_el.count():
                comments = _parse_compact_count(comments_el.inner_text())

            # Method 3: video player info (for clips/videos)
            info_el = page.locator(".vp-layer-info_cnt").first
            if info_el.count():
                info_text = info_el.inner_text()
                views_match = re.search(
                    r"([\d.,]+\s*(?:тыс|млн|млрд|[KkMmBb])?)\s*(?:просмотр|views?)",
                    info_text, re.I,
                )
                if views_match:
                    views = _parse_compact_count(views_match.group(1))

            # Method 4: topic-level metrics via data-l attributes
            if likes == 0:
                like_els = page.locator('[data-l*="like"]').all()
                for el in like_els:
                    cnt_el = el.locator(".widget_count").first
                    if cnt_el.count():
                        likes = _parse_compact_count(cnt_el.inner_text())
                        break

            # Extract hashtags
            hashtags: list[str] = []
            for selector in ["h1", ".vp-layer-info_title", ".video-card_title", ".feed_ct-text"]:
                el = page.locator(selector).first
                if el.count():
                    hashtags.extend(extract_hashtags(el.inner_text()))

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


async def _fetch_via_browser(url: str) -> Metrics:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_ok_page_playwright_sync, url),
            timeout=_OK_BROWSER_TIMEOUT,
        )
    except asyncio.TimeoutError as exc:
        raise ParserUnavailableError(f"OK browser fetch timed out ({_OK_BROWSER_TIMEOUT}s): {url}") from exc
