import asyncio
import re

import httpx

from app.parsers._jsonld import extract_interaction_counts
from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.parsers.ytdlp_common import fetch_via_ytdlp
from app.services.hashtag_extractor import extract_hashtags
from app.services.proxy_routing import get_proxy_for_platform


def _parse_compact_count(value: str | None) -> int:
    if not value:
        return 0
    normalized = value.strip().lower().replace("\xa0", " ").replace(",", ".")
    match = re.search(r"(\d+(?:\.\d+)?)", normalized)
    if not match:
        return 0
    number = float(match.group(1))
    if "млрд" in normalized:
        number *= 1_000_000_000
    elif "млн" in normalized:
        number *= 1_000_000
    elif "тыс" in normalized or normalized.endswith("k"):
        number *= 1_000
    return int(number)


def _fetch_via_playwright_sync(url: str) -> Metrics:
    """Fetch Dzen article/shorts metrics via headless Chromium.

    Dzen articles are behind Yandex SSO for plain HTTP requests, so a real
    browser is required.

    Article selectors:
    - Views:   [data-testid="article-info-block"] text with "тыс"/"млн"/digits
    - Likes:   button with class containing "button-like" (has count as text)
    - Comments: button[aria-label="Комментировать"] (has count as text)

    Shorts selectors:
    - Likes:   [data-testid="short-likes-counter"] or button[aria-label="Нравится"]
    - Comments: second social control item (sibling of likes counter)
    - Views:   not exposed on shorts pages
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ParserUnavailableError("Playwright is not installed") from exc

    is_shorts = "/shorts/" in url

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
                raise ParserNotFoundError(f"DZEN_CONTENT_NOT_FOUND: Dzen post not found: {url}")

            # Wait for page content to render
            if is_shorts:
                # Shorts: wait for social controls to appear
                try:
                    page.wait_for_selector('[class*="social-controls"]', timeout=10_000)
                except Exception:
                    title = page.title()
                    if "не найден" in title.lower() or "not found" in title.lower():
                        raise ParserNotFoundError(f"DZEN_CONTENT_NOT_FOUND: Dzen post not found: {url}")
                    raise ParserUnavailableError(f"DZEN_NO_SHORTS_CONTROLS: Dzen shorts page did not render controls: {url}")

                # Extract likes from short-likes-counter testid
                likes = 0
                likes_el = page.locator('[data-testid="short-likes-counter"]').first
                if likes_el.count():
                    likes = _parse_compact_count(likes_el.inner_text())
                else:
                    # Fallback: button with aria-label="Нравится"
                    like_btn = page.locator('button[aria-label="Нравится"]').first
                    if like_btn.count():
                        likes = _parse_compact_count(like_btn.inner_text())

                # Extract comments: second social control count (sibling of likes)
                comments = 0
                social_counts = page.locator('[class*="socialCount"]').all()
                if len(social_counts) >= 2:
                    comments = _parse_compact_count(social_counts[1].inner_text())

                # Shorts don't expose view counts
                views = 0
            else:
                # Article path
                try:
                    page.wait_for_selector(
                        '[data-testid="article-info-block"]',
                        timeout=10_000,
                    )
                except Exception:
                    title = page.title()
                    if "не найден" in title.lower() or "not found" in title.lower():
                        raise ParserNotFoundError(f"DZEN_CONTENT_NOT_FOUND: Dzen post not found: {url}")
                    raise ParserUnavailableError(f"DZEN_NO_ARTICLE_BLOCK: Dzen page did not render article block: {url}")

                # Extract views from the article-info-block.
                views = 0
                views_info = page.locator('[data-testid="article-info-block"]').first
                if views_info.count():
                    info_text = views_info.inner_text()
                    for line in info_text.split("\n"):
                        line = line.strip()
                        if re.search(r"\d", line) and ("тыс" in line.lower() or "млн" in line.lower() or "млрд" in line.lower() or re.match(r"^[\d\s,.]+$", line)):
                            views = _parse_compact_count(line)
                            break

                # Extract likes: button with class containing "button-like"
                likes = 0
                like_btn = page.locator('button[class*="button-like__buttonLike"]').first
                if like_btn.count():
                    likes = _parse_compact_count(like_btn.inner_text())

                # Extract comments: button with aria-label="Комментировать"
                comments = 0
                comment_btn = page.locator('[aria-label="Комментировать"]').first
                if comment_btn.count():
                    comments = _parse_compact_count(comment_btn.inner_text())

            # Extract hashtags from article/shorts title and content (not chrome)
            hashtags = []
            # Try article title
            title_el = page.locator("h1, [data-testid='article-title'], [class*='short-item-meta__title']").first
            if title_el.count():
                hashtags.extend(extract_hashtags(title_el.inner_text()))
            # Try article body
            body_el = page.locator("[data-testid='article-body'], [class*='article__body'], [class*='short-item-meta__description']").first
            if body_el.count():
                for h in extract_hashtags(body_el.inner_text()):
                    if h not in hashtags:
                        hashtags.append(h)

        finally:
            browser.close()

    if views == 0 and likes == 0 and comments == 0:
        raise ParserUnavailableError(f"DZEN_NO_METRICS: Dzen rendered no public metrics: {url}")

    return Metrics(
        likes=likes,
        reposts=0,
        comments=comments,
        saves=0,
        views=views,
        hashtags=hashtags,
    )


_DZEN_BROWSER_TIMEOUT = 45  # seconds — hard cap for Dzen Playwright fetch


async def _fetch_via_browser(url: str) -> Metrics:
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_via_playwright_sync, url),
            timeout=_DZEN_BROWSER_TIMEOUT,
        )
    except asyncio.TimeoutError:
        raise ParserUnavailableError(f"Dzen browser fetch timed out ({_DZEN_BROWSER_TIMEOUT}s): {url}")


async def fetch(url: str) -> Metrics:
    """Fetch Dzen metrics.

    Strategy:
    1. Try yt-dlp for video URLs (dzen.ru/video/watch/*, etc.) — returns views only.
    2. Try plain HTTP + JSON-LD extraction (best-effort, usually blocked by SSO).
    3. Fall back to Playwright headless browser for articles.
    """
    # Strip tracking params for cleaner URLs
    clean_url = url.split("?")[0] if "?" in url else url

    # Step 1: yt-dlp for video pages
    try:
        ytdlp_metrics = await fetch_via_ytdlp(clean_url)
    except (ParserNotFoundError, ParserUnavailableError):
        pass
    else:
        return Metrics(
            likes=0,
            reposts=0,
            comments=0,
            saves=0,
            views=ytdlp_metrics.views,
        )

    # Step 2: Try plain HTTP + JSON-LD (usually fails due to SSO redirect)
    try:
        async with httpx.AsyncClient(
            timeout=10, follow_redirects=True, proxy=get_proxy_for_platform("dzen")
        ) as client:
            response = await client.get(clean_url, headers={"User-Agent": "Mozilla/5.0"})

        if response.status_code == 404:
            raise ParserNotFoundError(f"DZEN_CONTENT_NOT_FOUND: Dzen post not found: {clean_url}")

        # Check if we got redirected to SSO (passport.yandex) — that means no real content
        if "passport.yandex" not in str(response.url) and response.status_code == 200:
            counts = extract_interaction_counts(response.text)
            if counts and any(v > 0 for v in counts.values()):
                return Metrics(
                    likes=counts.get("likes", 0),
                    reposts=counts.get("reposts", 0),
                    comments=counts.get("comments", 0),
                    saves=0,
                    views=counts.get("views", 0),
                )
    except ParserNotFoundError:
        raise
    except Exception:
        pass  # Fall through to browser

    # Step 3: Playwright browser (reliable but heavier)
    return await _fetch_via_browser(clean_url)
