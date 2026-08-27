import asyncio
import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

from app.core.config import settings
from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.services.hashtag_extractor import extract_hashtags
from app.services.proxy import normalize_proxy
from app.services.proxy_routing import get_proxy_for_platform

def _parse_public_count(value: str) -> int:
    """Parse Instagram's English public meta description counters."""
    cleaned = value.lower().replace("\xa0", " ").replace(",", "")
    match = re.search(r"(\d+(?:\.\d+)?)\s*([km]?)", cleaned)
    if not match:
        return 0
    count = float(match.group(1))
    if match.group(2) == "k":
        count *= 1_000
    elif match.group(2) == "m":
        count *= 1_000_000
    return int(count)


def _fetch_public_sync(url: str) -> Metrics:
    """Read public post counters from Instagram.

    Strategy:
    1. Try embed page via httpx (exact numbers for posts/carousels).
    2. Fall back to og:description parsing for posts with stats.
    3. For Reels: use Playwright to render the page and extract like_count/comment_count from HTML.
    """
    proxy_url = get_proxy_for_platform("instagram") or normalize_proxy(settings.instagram_proxy)
    clean_url = url.replace("/reels/", "/reel/").rstrip("/")

    embed_url = clean_url + "/embed/"
    headers = {"User-Agent": "Mozilla/5.0"}
    likes = 0
    comments = 0
    views = 0

    # Step 1: Try embed page (returns exact numbers for posts/carousels)
    for _ in range(2):
        try:
            with httpx.Client(proxy=proxy_url, timeout=15, follow_redirects=True) as client:
                response = client.get(embed_url, headers=headers)
            if response.status_code == 200:
                html = response.text
                likes_match = re.search(r'"likes_count":\s*(\d+)', html)
                if likes_match:
                    likes = int(likes_match.group(1))
                if not likes:
                    edge_match = re.search(r'"edge_media_preview_like":\s*\{[^}]*"count":\s*(\d+)', html)
                    if edge_match:
                        likes = int(edge_match.group(1))
                comments_match = re.search(r'"comments_count":\s*(\d+)', html)
                if comments_match:
                    comments = int(comments_match.group(1))
                views_match = re.search(r'"video_view_count":\s*(\d+)', html)
                if views_match:
                    views = int(views_match.group(1))
                if likes or comments or views:
                    break
        except httpx.HTTPError:
            pass

    # Step 2: Fall back to og:description (posts/carousels with "X likes, Y comments")
    if not likes and not comments:
        for _ in range(2):
            try:
                with httpx.Client(proxy=proxy_url, timeout=15, follow_redirects=True) as client:
                    response = client.get(clean_url, headers=headers)
                if response.status_code == 200:
                    desc = BeautifulSoup(response.text, "html.parser").find(
                        "meta", attrs={"property": "og:description"}
                    )
                    content = desc.get("content", "") if desc else ""
                    match = re.search(
                        r"([\d.,]+\s*[km]?)\s+likes?,\s*([\d.,]+\s*[km]?)\s+comments?",
                        content, re.IGNORECASE,
                    )
                    if match:
                        likes = _parse_public_count(match.group(1))
                        comments = _parse_public_count(match.group(2))
                        break
            except httpx.HTTPError:
                pass

    # Step 3: For Reels — use Playwright to intercept network JSON + embedded JSON
    shares = 0
    saves = 0
    if not likes and not comments and "/reel/" in clean_url:
        likes, comments, views, shares, saves = _fetch_reel_via_playwright(clean_url, proxy_url)

    if not likes and not comments and not views:
        raise ParserUnavailableError("Instagram did not expose engagement metrics")

    return Metrics(
        likes=likes,
        reposts=shares,
        comments=comments,
        saves=saves,
        views=views,
    )


def _fetch_reel_via_playwright(url: str, proxy_url: str | None) -> tuple[int, int, int, int, int]:
    """Fetch Reel metrics via headless browser.

    Strategy (from instagram_browser_parser):
    1. Intercept GraphQL/API JSON responses for full media data.
    2. Parse embedded JSON from <script> tags.
    3. Fallback to like_count/comment_count from HTML source.

    Returns: (likes, comments, views, shares, saves)
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return 0, 0, 0, 0, 0

    likes, comments, views, shares, saves = 0, 0, 0, 0, 0

    _COUNT_MAP = {
        "likes": ("like_count", "likes_count"),
        "comments": ("comment_count", "comments_count"),
        "views": ("view_count", "video_view_count", "views_count", "ig_play_count"),
        "shares": ("share_count", "shares_count", "reshare_count"),
        "saves": ("save_count", "saved_count", "saves_count"),
    }

    def _extract_from_dict(d: dict) -> dict:
        result = {}
        for field, aliases in _COUNT_MAP.items():
            for alias in aliases:
                if alias in d and d[alias] is not None:
                    try:
                        result[field] = int(d[alias])
                        break
                    except (ValueError, TypeError):
                        pass
        # views fallback: play_count
        if "views" not in result and "plays" not in result:
            for alias in ("play_count", "video_play_count"):
                if alias in d and d[alias] is not None:
                    try:
                        result["views"] = int(d[alias])
                        break
                    except (ValueError, TypeError):
                        pass
        return result

    def _walk(obj):
        if isinstance(obj, dict):
            yield obj
            for v in obj.values():
                yield from _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                yield from _walk(v)

    def _score(d: dict, shortcode: str) -> int:
        score = 0
        code = d.get("code") or d.get("shortcode")
        if code == shortcode:
            score += 100
        if d.get("product_type") in ("clips", "reel"):
            score += 10
        if d.get("__typename") == "GraphVideo":
            score += 5
        for aliases in _COUNT_MAP.values():
            if any(d.get(a) is not None for a in aliases):
                score += 3
        return score

    captured: list = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context_kwargs: dict = {
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
            "locale": "en-US",
        }
        if proxy_url:
            parsed = urlparse(proxy_url)
            context_kwargs["proxy"] = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                "username": parsed.username,
                "password": parsed.password,
            }
        context = browser.new_context(**context_kwargs)
        page = context.new_page()

        def _on_response(response):
            resp_url = response.url.lower()
            if not any(x in resp_url for x in ("/api/graphql", "/graphql/query", "/api/v1/")):
                return
            ct = ""
            try:
                ct = response.headers.get("content-type", "")
            except Exception:
                pass
            if "json" not in ct and "graphql" not in resp_url:
                return
            try:
                captured.append(response.json())
            except Exception:
                pass

        page.on("response", _on_response)

        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25_000)
            page.wait_for_timeout(4500)
            page.mouse.wheel(0, 500)
            page.wait_for_timeout(1500)

            shortcode = url.rstrip("/").split("/")[-1]

            # Step 1: Check network JSON for full media data
            best = None
            best_score = 0
            for payload in captured:
                for d in _walk(payload):
                    s = _score(d, shortcode)
                    if s > best_score:
                        best_score = s
                        best = d

            if best and best_score >= 6:
                metrics = _extract_from_dict(best)
                likes = metrics.get("likes", 0)
                comments = metrics.get("comments", 0)
                views = metrics.get("views", 0)
                shares = metrics.get("shares", 0)
                saves = metrics.get("saves", 0)

            # Step 2: Embedded JSON from script tags
            if not likes and not comments:
                scripts = page.locator("script").all_text_contents()
                for raw in scripts:
                    raw = raw.strip()
                    if not raw or raw[0] not in "[{":
                        continue
                    try:
                        import json
                        data = json.loads(raw)
                        for d in _walk(data):
                            s = _score(d, shortcode)
                            if s > best_score:
                                best_score = s
                                best = d
                    except Exception:
                        pass

                if best and best_score >= 6:
                    metrics = _extract_from_dict(best)
                    likes = metrics.get("likes", likes)
                    comments = metrics.get("comments", comments)
                    views = metrics.get("views", views)
                    shares = metrics.get("shares", shares)
                    saves = metrics.get("saves", saves)

            # Step 3: Fallback to HTML regex
            if not likes and not comments:
                html = page.content()
                m = re.search(r'"like_count":\s*(\d+)', html)
                if m:
                    likes = int(m.group(1))
                m = re.search(r'"comment_count":\s*(\d+)', html)
                if m:
                    comments = int(m.group(1))

        except Exception:
            pass
        finally:
            browser.close()

    return likes, comments, views, shares, saves


_INSTAGRAM_TIMEOUT = 45  # seconds — hard cap for any Instagram fetch


async def _fetch_via_calcxi(url: str) -> Metrics:
    """Fetch Instagram Reel metrics via Calcxi (buffer site). Returns shares."""
    import sys
    sys.path.insert(0, "/app")
    from instagram_calcxi_parser import scrape_calcxi

    result = await scrape_calcxi(url, timeout_ms=60_000)
    caption = result.caption or ""

    return Metrics(
        likes=result.likes or 0,
        reposts=result.shares or 0,
        comments=result.comments or 0,
        saves=result.saves or 0,
        views=result.views or 0,
        hashtags=extract_hashtags(caption),
    )


def _fetch_via_direct_graphql(url: str) -> Metrics:
    """Fetch Instagram post metrics via logged-out GraphQL API (no login needed)."""
    import json as _json
    import html as _html_lib
    from curl_cffi import requests as http

    IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"
    GRAPHQL_DOC_ID = "27130156389949648"
    GRAPHQL_FRIENDLY_NAME = "PolarisLoggedOutDesktopWWWPostRootContentQuery"
    BASE = "https://www.instagram.com"

    clean_url = url.replace("/reels/", "/reel/").rstrip("/")
    # Extract shortcode
    parts = [p for p in clean_url.split("/") if p]
    shortcode = None
    for i, p in enumerate(parts):
        if p in ("p", "reel", "reels", "tv") and i + 1 < len(parts):
            shortcode = parts[i + 1]
            break
    if not shortcode:
        raise ParserNotFoundError(f"Cannot extract shortcode from {url}")

    # Shortcode to media ID
    sc = shortcode
    if len(sc) > 28:
        sc = sc[:-28]
    media_id = 0
    for ch in sc:
        media_id = media_id * 64 + IG_ALPHABET.index(ch)
    media_id = str(media_id)

    proxy_url = get_proxy_for_platform("instagram") or normalize_proxy(settings.instagram_proxy)
    proxy_str = None
    if proxy_url:
        from urllib.parse import urlparse as _urlparse
        parsed = _urlparse(proxy_url)
        proxy_str = f"http://{parsed.username}:{parsed.password}@{parsed.hostname}:{parsed.port}"

    session = http.Session(impersonate="chrome", proxy=proxy_str)

    # 1. Get LSD token from homepage
    home = session.get(BASE + "/", timeout=15)
    home.raise_for_status()

    lsd = None
    for pat in [r'\["LSD",\[\],\{"token":"([^"]+)"', r'"LSD",\[\],\{"token":"([^"]+)"']:
        m = re.search(pat, home.text)
        if m:
            lsd = _html_lib.unescape(m.group(1))
            break
    if not lsd:
        raise ParserUnavailableError("Instagram did not return LSD token")

    # 2. GraphQL request
    canonical = f"{BASE}/p/{shortcode}/"
    headers = {
        "Accept": "*/*",
        "Origin": BASE,
        "X-IG-App-ID": "936619743392459",
        "X-ASBD-ID": "359341",
        "X-IG-WWW-Claim": "0",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
        "Content-Type": "application/x-www-form-urlencoded",
        "X-FB-Friendly-Name": GRAPHQL_FRIENDLY_NAME,
        "X-FB-LSD": lsd,
        "X-Requested-With": "XMLHttpRequest",
        "Referer": canonical,
    }

    csrf = session.cookies.get("csrftoken")
    if csrf:
        headers["X-CSRFToken"] = csrf

    payload = {
        "lsd": lsd,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": GRAPHQL_FRIENDLY_NAME,
        "server_timestamps": "true",
        "variables": _json.dumps({"media_id": media_id}, separators=(",", ":")),
        "doc_id": GRAPHQL_DOC_ID,
    }

    response = session.post(f"{BASE}/api/graphql", headers=headers, data=payload, timeout=15)

    if response.status_code == 429:
        raise ParserUnavailableError("Instagram rate limit (429)")
    if response.status_code != 200:
        raise ParserUnavailableError(f"Instagram GraphQL returned {response.status_code}")

    data = response.json()
    d = data.get("data", {})
    polaris = d.get("xig_polaris_media", {})
    media = (polaris.get("if_not_gated_logged_out") or polaris) if isinstance(polaris, dict) else None

    if not media:
        raise ParserNotFoundError(f"Instagram post not found: {url}")

    likes = media.get("like_count") or 0
    comments = media.get("comment_count") or 0
    caption = ""
    cap = media.get("caption")
    if isinstance(cap, dict):
        caption = cap.get("text") or ""
    elif isinstance(cap, str):
        caption = cap

    return Metrics(
        likes=likes,
        reposts=0,
        comments=comments,
        saves=0,
        views=media.get("play_count") or media.get("video_view_count") or 0,
        hashtags=extract_hashtags(caption),
    )


async def fetch(url: str) -> Metrics:
    clean_url = url.replace("/reels/", "/reel/").rstrip("/")
    is_reel = "/reel/" in clean_url
    calcxi_result: Metrics | None = None

    def _merge_metrics(primary: Metrics, fallback: Metrics | None) -> Metrics:
        if fallback is None:
            return primary
        return Metrics(
            likes=primary.likes or fallback.likes,
            reposts=primary.reposts or fallback.reposts,
            comments=primary.comments or fallback.comments,
            saves=primary.saves or fallback.saves,
            views=primary.views or fallback.views,
            hashtags=primary.hashtags or fallback.hashtags,
        )

    def _complete_enough(metrics: Metrics) -> bool:
        if not is_reel:
            return bool(metrics.likes or metrics.comments)
        # Reels sources expose different subsets. Continue to other sources
        # when Calcxi only returned likes/views.
        return bool(metrics.views and metrics.likes and metrics.comments and metrics.hashtags)

    # Strategy 1: Calcxi (free — Reels only, returns views/shares/saves)
    if is_reel:
        try:
            calcxi = await asyncio.wait_for(_fetch_via_calcxi(url), timeout=90)
            if calcxi.views or calcxi.likes or calcxi.comments or calcxi.reposts or calcxi.saves:
                calcxi_result = calcxi
                if _complete_enough(calcxi):
                    return calcxi
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    # Strategy 2: Direct GraphQL (free, needs proxy — posts/carousels, exact likes/comments)
    has_proxy = bool(get_proxy_for_platform("instagram") or settings.instagram_proxy)
    if has_proxy:
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(_fetch_via_direct_graphql, url),
                timeout=30,
            )
            if result.likes or result.comments:
                return _merge_metrics(result, calcxi_result)
        except asyncio.TimeoutError:
            pass
        except Exception:
            pass

    # Strategy 3: Public page scraping (fallback)
    if has_proxy:
        try:
            public_result = await asyncio.wait_for(
                asyncio.to_thread(_fetch_public_sync, url),
                timeout=_INSTAGRAM_TIMEOUT,
            )
            return _merge_metrics(public_result, calcxi_result)
        except asyncio.TimeoutError:
            raise ParserUnavailableError(f"Instagram public fetch timed out ({_INSTAGRAM_TIMEOUT}s): {url}")
        except ParserNotFoundError:
            raise
        except ParserUnavailableError:
            pass

    if calcxi_result:
        return calcxi_result

    raise ParserUnavailableError(
        "INSTAGRAM_CONFIG_MISSING: Instagram requires proxy (NON_RU_PROXY) for direct GraphQL, "
        "or public Reel scraping via Calcxi."
    )
