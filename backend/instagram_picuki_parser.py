#!/usr/bin/env python3
"""
Instagram post / carousel parser through Picuki Post Viewer.

Source:
    https://picuki.site/instagram-post-viewer

Supports:
    - /p/ single image posts
    - /p/ single video posts
    - /p/ carousel posts

Returns:
    - type: image | video | carousel
    - likes
    - caption
    - author (when exposed)
    - published_at (when exposed)
    - media[] in upload/display order

Important:
    Picuki's current Post Viewer intentionally does NOT expose comments,
    so comments=None is expected.

No Instagram login, sessionid, Meta token, Apify token or RapidAPI key.

Install:
    pip install playwright
    playwright install chromium

Usage:
    python instagram_picuki_parser.py \
      "https://www.instagram.com/p/SHORTCODE/"

Debug:
    python instagram_picuki_parser.py URL --debug

Visible browser:
    python instagram_picuki_parser.py URL --headed
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse, urljoin

from playwright.async_api import async_playwright, Page, Response


PICUKI_URL = "https://picuki.site/instagram-post-viewer"


class PicukiError(RuntimeError):
    pass


@dataclass
class MediaItem:
    index: int
    type: str               # image | video
    url: str
    thumbnail_url: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class InstagramPost:
    input_url: str
    source: str = "picuki"
    shortcode: str | None = None
    type: str | None = None  # image | video | carousel
    likes: int | None = None
    comments: int | None = None
    caption: str | None = None
    author: str | None = None
    published_at: str | None = None
    media: list[MediaItem] | None = None
    extraction_source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["media"] = [m.to_dict() for m in (self.media or [])]
        return data


def extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if not (
        host == "instagram.com"
        or host.endswith(".instagram.com")
        or host == "instagr.am"
        or host.endswith(".instagr.am")
    ):
        raise ValueError("Нужна ссылка Instagram")

    parts = [p for p in parsed.path.split("/") if p]
    if "p" not in parts:
        raise ValueError(
            "Этот парсер предназначен для обычных Instagram-постов /p/ "
            "(включая карусели). Для /reel/ используй Calcxi parser."
        )

    i = parts.index("p")
    if i + 1 >= len(parts):
        raise ValueError("Не удалось получить shortcode из URL")

    return parts[i + 1]


def canonical_post_url(url: str) -> str:
    code = extract_shortcode(url)
    return f"https://www.instagram.com/p/{code}/"


def to_number(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return int(value)

    text = str(value).strip()
    if not text or text.lower() in {"null", "none", "n/a", "-", "—"}:
        return None

    match = re.search(r"([\d.,]+)\s*([KMB])?", text, re.I)
    if not match:
        return None

    raw = match.group(1)
    suffix = (match.group(2) or "").upper()

    if suffix:
        raw = raw.replace(",", "")
        try:
            number = float(raw)
        except ValueError:
            return None
    else:
        # Like counts can be "12,345" or "12.345" depending locale.
        # Treat separators as thousands when no suffix exists.
        raw = raw.replace(",", "").replace(".", "")
        try:
            number = float(raw)
        except ValueError:
            return None

    multiplier = {
        "": 1,
        "K": 1_000,
        "M": 1_000_000,
        "B": 1_000_000_000,
    }[suffix]

    return int(number * multiplier)


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


LIKE_ALIASES = (
    "likes",
    "like_count",
    "likeCount",
    "likesCount",
    "edge_media_preview_like",
    "edge_liked_by",
)

CAPTION_ALIASES = (
    "caption",
    "description",
    "text",
    "full_caption",
    "fullCaption",
)

AUTHOR_ALIASES = (
    "username",
    "author",
    "ownerUsername",
    "owner_username",
)

DATE_ALIASES = (
    "published_at",
    "publishedAt",
    "timestamp",
    "taken_at",
    "takenAt",
    "date",
)

IMAGE_ALIASES = (
    "display_url",
    "displayUrl",
    "image_url",
    "imageUrl",
    "thumbnail_url",
    "thumbnailUrl",
)

VIDEO_ALIASES = (
    "video_url",
    "videoUrl",
    "download_url",
    "downloadUrl",
)


def _edge_count(value: Any) -> int | None:
    if isinstance(value, dict):
        return to_number(value.get("count"))
    return to_number(value)


def _first(d: dict[str, Any], keys: tuple[str, ...]) -> Any:
    for key in keys:
        if key in d and d[key] not in (None, "", "-", "—"):
            return d[key]
    return None


def _extract_media_from_dict(d: dict[str, Any]) -> list[MediaItem]:
    media: list[MediaItem] = []

    # Common carousel shapes.
    carousel_keys = (
        "carousel_media",
        "carouselMedia",
        "resources",
        "slides",
        "items",
        "children",
        "edge_sidecar_to_children",
    )

    for key in carousel_keys:
        value = d.get(key)

        # Instagram GraphQL-style:
        # edge_sidecar_to_children: {"edges": [{"node": {...}}, ...]}
        if isinstance(value, dict) and isinstance(value.get("edges"), list):
            nodes = []
            for edge in value["edges"]:
                if isinstance(edge, dict) and isinstance(edge.get("node"), dict):
                    nodes.append(edge["node"])
            value = nodes

        if not isinstance(value, list):
            continue

        tmp: list[MediaItem] = []
        for idx, child in enumerate(value):
            if not isinstance(child, dict):
                continue

            video = _first(child, VIDEO_ALIASES)
            image = _first(child, IMAGE_ALIASES)

            if isinstance(video, str) and video.startswith("http"):
                tmp.append(
                    MediaItem(
                        index=idx,
                        type="video",
                        url=video,
                        thumbnail_url=image if isinstance(image, str) else None,
                    )
                )
            elif isinstance(image, str) and image.startswith("http"):
                tmp.append(
                    MediaItem(
                        index=idx,
                        type="image",
                        url=image,
                    )
                )

        if tmp:
            return tmp

    # Single-media object.
    video = _first(d, VIDEO_ALIASES)
    image = _first(d, IMAGE_ALIASES)

    if isinstance(video, str) and video.startswith("http"):
        media.append(
            MediaItem(
                index=0,
                type="video",
                url=video,
                thumbnail_url=image if isinstance(image, str) else None,
            )
        )
    elif isinstance(image, str) and image.startswith("http"):
        media.append(
            MediaItem(
                index=0,
                type="image",
                url=image,
            )
        )

    return media


def post_from_json(payload: Any, input_url: str) -> InstagramPost | None:
    """
    Look through every JSON object returned by Picuki and select the object
    that looks most like an Instagram post.
    """
    code = extract_shortcode(input_url)

    best: InstagramPost | None = None
    best_score = 0

    for d in _walk(payload):
        candidate = InstagramPost(
            input_url=canonical_post_url(input_url),
            shortcode=code,
            extraction_source="network-json",
            comments=None,  # Picuki intentionally doesn't expose comments.
        )
        score = 0

        # Prefer objects carrying the same shortcode/code.
        obj_code = (
            d.get("shortcode")
            or d.get("shortCode")
            or d.get("code")
        )
        if obj_code == code:
            score += 100
        elif isinstance(obj_code, str):
            score -= 10

        raw_likes = _first(d, LIKE_ALIASES)
        likes = _edge_count(raw_likes)
        if likes is not None:
            candidate.likes = likes
            score += 5

        caption = _first(d, CAPTION_ALIASES)
        if isinstance(caption, dict):
            caption = caption.get("text")
        if isinstance(caption, str) and caption.strip():
            candidate.caption = caption.strip()
            score += 2

        author = _first(d, AUTHOR_ALIASES)
        if isinstance(author, dict):
            author = author.get("username")
        if isinstance(author, str) and author.strip():
            candidate.author = author.strip()
            score += 1

        published = _first(d, DATE_ALIASES)
        if published is not None:
            candidate.published_at = str(published)
            score += 1

        media = _extract_media_from_dict(d)
        if media:
            candidate.media = media
            score += 6 + len(media)

            if len(media) > 1:
                candidate.type = "carousel"
            else:
                candidate.type = media[0].type

        # Native Instagram hints.
        typename = str(d.get("__typename") or d.get("media_type") or "").lower()
        if "sidecar" in typename or "carousel" in typename:
            candidate.type = "carousel"
            score += 3

        if score > best_score:
            best_score = score
            best = candidate

    return best if best_score >= 5 else None


def post_from_text(text: str, input_url: str) -> InstagramPost | None:
    """
    Text fallback for fields that Picuki visibly documents:
      - like count
      - full caption

    Media itself is extracted from the DOM separately.
    """
    code = extract_shortcode(input_url)

    result = InstagramPost(
        input_url=canonical_post_url(input_url),
        shortcode=code,
        extraction_source="dom",
        comments=None,
    )
    found = 0

    like_patterns = (
        r"\bLikes?\b\s*[:\n\r\t ]+\s*([\d.,]+\s*[KMB]?)",
        r"([\d.,]+\s*[KMB]?)\s+\bLikes?\b",
    )

    for pattern in like_patterns:
        m = re.search(pattern, text, re.I)
        if m:
            result.likes = to_number(m.group(1))
            if result.likes is not None:
                found += 1
                break

    # Conservative caption extraction.
    caption_patterns = (
        r"(?:Full\s+)?Caption\s*[:\n]+\s*(.+?)(?=\n\s*(?:Download|Likes?|Date|Post|Media)\b|\Z)",
        r"\bCaption\b\s*[:\n]+\s*(.+?)(?=\n{2,}|\Z)",
    )

    for pattern in caption_patterns:
        m = re.search(pattern, text, re.I | re.S)
        if m:
            caption = m.group(1).strip()
            if 0 < len(caption) <= 10_000:
                result.caption = caption
                found += 1
                break

    return result if found else None


def _clean_media_url(url: str | None) -> str | None:
    if not url:
        return None
    url = url.strip()
    if url.startswith("//"):
        return "https:" + url
    return url


def _looks_like_content_media(url: str) -> bool:
    low = url.lower()

    bad = (
        "logo",
        "favicon",
        "avatar",
        "icon",
        "sprite",
        "form-btn",
        "/ads/",
        "doubleclick",
        "googleads",
    )
    if any(x in low for x in bad):
        return False

    return (
        url.startswith("http")
        and any(
            x in low
            for x in (
                ".jpg",
                ".jpeg",
                ".png",
                ".webp",
                ".mp4",
                "instagram",
                "cdn",
                "media",
                "download",
                "proxy",
            )
        )
    )


async def media_from_dom(page: Page) -> list[MediaItem]:
    """
    Extract visible result media from the rendered Picuki page.

    Heuristics intentionally ignore small logos/icons/avatars.
    """
    found: list[MediaItem] = []
    seen: set[str] = set()

    # Prefer result-ish containers, but fall back to entire page.
    container_selectors = [
        "main",
        "article",
        '[class*="result" i]',
        '[class*="post" i]',
        '[class*="media" i]',
        "body",
    ]

    root = None
    for selector in container_selectors:
        loc = page.locator(selector)
        if await loc.count():
            root = loc.first
            break

    if root is None:
        return []

    # Videos first.
    videos = root.locator("video")
    for i in range(await videos.count()):
        el = videos.nth(i)

        src = _clean_media_url(await el.get_attribute("src"))
        if not src:
            source = el.locator("source")
            if await source.count():
                src = _clean_media_url(await source.first.get_attribute("src"))

        if not src or not _looks_like_content_media(src) or src in seen:
            continue

        poster = _clean_media_url(await el.get_attribute("poster"))
        seen.add(src)
        found.append(
            MediaItem(
                index=len(found),
                type="video",
                url=src,
                thumbnail_url=poster,
            )
        )

    # Images.
    images = root.locator("img")
    for i in range(await images.count()):
        el = images.nth(i)

        src = (
            await el.get_attribute("src")
            or await el.get_attribute("data-src")
            or await el.get_attribute("data-lazy-src")
        )
        src = _clean_media_url(src)

        if not src or not _looks_like_content_media(src) or src in seen:
            continue

        # Avoid tiny decorative images when dimensions are available.
        try:
            box = await el.bounding_box()
        except Exception:
            box = None

        if box and (box["width"] < 180 or box["height"] < 180):
            continue

        seen.add(src)
        found.append(
            MediaItem(
                index=len(found),
                type="image",
                url=src,
            )
        )

    return found


def merge_post(
    network: InstagramPost | None,
    dom: InstagramPost | None,
    dom_media: list[MediaItem],
    input_url: str,
) -> InstagramPost:
    if not network and not dom and not dom_media:
        raise PicukiError("Picuki не вернул распознаваемый пост")

    result = network or dom or InstagramPost(
        input_url=canonical_post_url(input_url),
        shortcode=extract_shortcode(input_url),
        comments=None,
        extraction_source="dom-media",
    )

    if dom:
        for field in ("likes", "caption", "author", "published_at"):
            if getattr(result, field) is None:
                setattr(result, field, getattr(dom, field))

    if not result.media and dom_media:
        result.media = dom_media

    media = result.media or []

    # Deduplicate while preserving order.
    deduped: list[MediaItem] = []
    seen: set[str] = set()
    for item in media:
        if item.url in seen:
            continue
        seen.add(item.url)
        item.index = len(deduped)
        deduped.append(item)
    result.media = deduped

    if len(deduped) > 1:
        result.type = "carousel"
    elif len(deduped) == 1:
        result.type = deduped[0].type

    return result


async def find_input(page: Page):
    selectors = [
        'input[type="url"]',
        'input[placeholder*="instagram" i]',
        'input[placeholder*="username" i]',
        'input[placeholder*="link" i]',
        'input[type="text"]',
    ]

    for selector in selectors:
        loc = page.locator(selector)
        for i in range(await loc.count()):
            el = loc.nth(i)
            if await el.is_visible():
                return el

    raise PicukiError("Не удалось найти поле для Instagram URL")


async def trigger_lookup(page: Page, input_box) -> None:
    """
    Picuki's page can change button wording. Try semantic submit buttons,
    then Enter in the input field.
    """
    candidates = [
        page.get_by_role("button", name=re.compile(r"view|open|search|show|submit|go", re.I)),
        page.locator('button[type="submit"]'),
        page.locator('input[type="submit"]'),
    ]

    for loc in candidates:
        for i in range(await loc.count()):
            btn = loc.nth(i)
            try:
                if await btn.is_visible() and await btn.is_enabled():
                    await btn.click()
                    return
            except Exception:
                pass

    # Some viewer forms submit directly on Enter.
    await input_box.press("Enter")


async def scrape_picuki(
    post_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
    debug: bool = False,
    proxy_server: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
) -> InstagramPost:
    extract_shortcode(post_url)  # validate

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

        if os.path.exists("/usr/bin/chromium"):
            launch_kwargs["executable_path"] = "/usr/bin/chromium"

        browser = await p.chromium.launch(**launch_kwargs)

        context_kwargs: dict[str, Any] = {
            "locale": "en-US",
            "viewport": {"width": 1365, "height": 1000},
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
            url_lower = response.url.lower()
            headers = await response.all_headers()
            content_type = headers.get("content-type", "").lower()

            if any(
                word in url_lower
                for word in (
                    "/api/",
                    "ajax",
                    "instagram",
                    "post",
                    "viewer",
                    "media",
                    "download",
                    "lookup",
                )
            ):
                interesting_requests.append(
                    {
                        "status": response.status,
                        "url": response.url,
                        "content_type": content_type,
                    }
                )

            if "json" in content_type:
                try:
                    captured_json.append(await response.json())
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            await page.goto(
                PICUKI_URL,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            # Region/service block detection.
            body_before = (await page.locator("body").inner_text()).lower()
            if "discontinuation of service" in body_before:
                raise PicukiError(
                    "Picuki заблокирован для текущего региона/IP. "
                    "Попробуй другой IP/прокси."
                )

            input_box = await find_input(page)
            await input_box.fill(canonical_post_url(post_url))
            await trigger_lookup(page, input_box)

            deadline = asyncio.get_running_loop().time() + timeout_ms / 1000

            network_result: InstagramPost | None = None
            dom_result: InstagramPost | None = None
            dom_media: list[MediaItem] = []

            while asyncio.get_running_loop().time() < deadline:
                # Network JSON is preferred.
                for payload in reversed(captured_json):
                    candidate = post_from_json(payload, post_url)
                    if candidate:
                        network_result = candidate
                        if candidate.media and candidate.likes is not None:
                            break

                text = await page.locator("body").inner_text()
                dom_result = post_from_text(text, post_url)
                dom_media = await media_from_dom(page)

                have_media = bool(
                    (network_result and network_result.media)
                    or dom_media
                )
                have_likes = bool(
                    (network_result and network_result.likes is not None)
                    or (dom_result and dom_result.likes is not None)
                )

                if have_media and have_likes:
                    # Allow lazy carousel slides to render.
                    await page.wait_for_timeout(1200)
                    newer_media = await media_from_dom(page)
                    if len(newer_media) > len(dom_media):
                        dom_media = newer_media
                    break

                # Try a small scroll to trigger lazy carousel/media loading.
                await page.mouse.wheel(0, 600)
                await page.wait_for_timeout(750)

            if debug:
                debug_payload = {
                    "picuki_page_url": page.url,
                    "captured_json_responses": len(captured_json),
                    "interesting_requests": list(
                        {
                            (x["status"], x["url"]): x
                            for x in interesting_requests
                        }.values()
                    ),
                    "dom_media_found": len(dom_media),
                }
                print(
                    json.dumps(debug_payload, ensure_ascii=False, indent=2),
                    file=sys.stderr,
                )

            result = merge_post(
                network_result,
                dom_result,
                dom_media,
                post_url,
            )

            if not result.media:
                raise PicukiError(
                    "Picuki открыл результат, но media поста/карусели не найдены."
                )

            return result

        finally:
            await context.close()
            await browser.close()


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse Instagram /p/ posts and carousels through Picuki"
    )
    parser.add_argument("url", help="Instagram /p/ URL")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Запустить Chromium с окном",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Показать network endpoints Picuki",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout seconds, default=60",
    )

    args = parser.parse_args()

    try:
        result = await scrape_picuki(
            args.url,
            headless=not args.headed,
            timeout_ms=args.timeout * 1000,
            debug=args.debug,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
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
