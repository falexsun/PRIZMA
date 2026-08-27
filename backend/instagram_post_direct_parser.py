#!/usr/bin/env python3
"""
Direct Instagram public-post/carousel parser (NO Apify, NO login).

Scope:
    https://www.instagram.com/p/SHORTCODE/

Returns:
    - post type: image | video | carousel
    - likes
    - comments
    - caption
    - author
    - published_at
    - media[] for every carousel slide

It uses Instagram's logged-out web GraphQL flow similar to current yt-dlp.
No Instagram username/password/sessionid is required.

Recommended install:
    pip install curl_cffi

Usage:
    python instagram_post_direct_parser.py \
        "https://www.instagram.com/p/SHORTCODE/"

Optional:
    python instagram_post_direct_parser.py URL --raw
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

try:
    from curl_cffi import requests as http
    HAS_CURL_CFFI = True
except ImportError:
    import requests as http
    HAS_CURL_CFFI = False


BASE = "https://www.instagram.com"
APP_ID = "936619743392459"
ASBD_ID = "359341"

# Current logged-out post-root query used by yt-dlp as of 2026.
GRAPHQL_DOC_ID = "27130156389949648"
GRAPHQL_FRIENDLY_NAME = "PolarisLoggedOutDesktopWWWPostRootContentQuery"

IG_ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"


class InstagramError(RuntimeError):
    pass


@dataclass
class MediaItem:
    index: int
    type: str              # image | video
    url: str | None
    thumbnail_url: str | None = None
    width: int | None = None
    height: int | None = None
    duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PostResult:
    url: str
    shortcode: str
    type: str | None
    likes: int | None
    comments: int | None
    caption: str | None
    author: str | None
    published_at: int | None
    media: list[MediaItem]
    source: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["media"] = [m.to_dict() for m in self.media]
        return data


def extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if "instagram.com" not in host:
        raise ValueError("Нужна ссылка Instagram")

    parts = [p for p in parsed.path.split("/") if p]

    if "p" not in parts:
        raise ValueError(
            "Этот парсер только для обычных /p/ постов и каруселей. "
            "Для Reels используй Calcxi."
        )

    i = parts.index("p")
    if i + 1 >= len(parts):
        raise ValueError("Не найден shortcode")

    return parts[i + 1]


def canonical_url(url: str) -> str:
    return f"{BASE}/p/{extract_shortcode(url)}/"


def shortcode_to_media_id(shortcode: str) -> str:
    """
    Instagram shortcode -> numeric media id.
    Same base64-like alphabet Instagram/yt-dlp uses.
    """
    if len(shortcode) > 28:
        shortcode = shortcode[:-28]

    value = 0
    for ch in shortcode:
        try:
            digit = IG_ALPHABET.index(ch)
        except ValueError as exc:
            raise ValueError(f"Недопустимый символ shortcode: {ch!r}") from exc
        value = value * 64 + digit

    return str(value)


def _session():
    if HAS_CURL_CFFI:
        return http.Session(impersonate="chrome")
    return http.Session()


def _headers(referer: str | None = None) -> dict[str, str]:
    headers = {
        "Accept": "*/*",
        "Origin": BASE,
        "X-IG-App-ID": APP_ID,
        "X-ASBD-ID": ASBD_ID,
        "X-IG-WWW-Claim": "0",
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/140.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-US,en;q=0.9",
    }

    if referer:
        headers["Referer"] = referer

    return headers


def _extract_lsd(home_html: str) -> str:
    patterns = [
        r'\["LSD",\[\],\{"token":"([^"]+)"',
        r'"LSD",\[\],\{"token":"([^"]+)"',
    ]

    for pattern in patterns:
        m = re.search(pattern, home_html)
        if m:
            return html_lib.unescape(m.group(1))

    # Backup: __eqmc JSON.
    m = re.search(
        r'<script\b[^>]*\bid=["\']__eqmc["\'][^>]*>(.*?)</script>',
        home_html,
        flags=re.S | re.I,
    )
    if m:
        try:
            data = json.loads(html_lib.unescape(m.group(1)).strip())
            token = data.get("l")
            if isinstance(token, str) and token:
                return token
        except Exception:
            pass

    raise InstagramError("Instagram не отдал logged-out LSD token")


def _as_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _first(d: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in d and d[key] is not None:
            return d[key]
    return None


def _extract_caption(media: dict[str, Any]) -> str | None:
    caption = media.get("caption")

    if isinstance(caption, dict):
        text = caption.get("text")
        if isinstance(text, str):
            return text

    if isinstance(caption, str):
        return caption

    edges = (
        media.get("edge_media_to_caption", {})
        if isinstance(media.get("edge_media_to_caption"), dict)
        else {}
    )
    edge_list = edges.get("edges")

    if isinstance(edge_list, list) and edge_list:
        node = edge_list[0].get("node") if isinstance(edge_list[0], dict) else None
        if isinstance(node, dict) and isinstance(node.get("text"), str):
            return node["text"]

    return None


def _extract_author(media: dict[str, Any]) -> str | None:
    user = media.get("user")
    if isinstance(user, dict) and isinstance(user.get("username"), str):
        return user["username"]

    owner = media.get("owner")
    if isinstance(owner, dict) and isinstance(owner.get("username"), str):
        return owner["username"]

    return None


def _extract_image_url(media: dict[str, Any]) -> tuple[str | None, int | None, int | None]:
    # Current product API.
    image_versions = media.get("image_versions2")
    if isinstance(image_versions, dict):
        candidates = image_versions.get("candidates")
        if isinstance(candidates, list) and candidates:
            # First candidate is usually the largest.
            c = candidates[0]
            if isinstance(c, dict):
                return (
                    c.get("url"),
                    _as_int(c.get("width")),
                    _as_int(c.get("height")),
                )

    # GraphQL style.
    display = _first(media, "display_url", "display_src", "thumbnail_src")

    dims = media.get("dimensions")
    width = height = None
    if isinstance(dims, dict):
        width = _as_int(dims.get("width"))
        height = _as_int(dims.get("height"))

    return (
        display if isinstance(display, str) else None,
        width,
        height,
    )


def _extract_video_url(media: dict[str, Any]) -> tuple[str | None, int | None, int | None]:
    versions = media.get("video_versions")

    if isinstance(versions, list) and versions:
        best = versions[0]
        if isinstance(best, dict):
            return (
                best.get("url"),
                _as_int(best.get("width")),
                _as_int(best.get("height")),
            )

    video_url = media.get("video_url")
    if isinstance(video_url, str):
        dims = media.get("dimensions")
        width = height = None
        if isinstance(dims, dict):
            width = _as_int(dims.get("width"))
            height = _as_int(dims.get("height"))
        return video_url, width, height

    return None, None, None


def _is_video(media: dict[str, Any]) -> bool:
    if media.get("is_video") is True:
        return True

    typename = str(media.get("__typename") or "").lower()
    if "video" in typename:
        return True

    media_type = media.get("media_type")
    if media_type == 2:
        return True

    return bool(media.get("video_versions") or media.get("video_url"))


def _media_item(media: dict[str, Any], index: int) -> MediaItem:
    if _is_video(media):
        video_url, width, height = _extract_video_url(media)
        thumb_url, _, _ = _extract_image_url(media)

        return MediaItem(
            index=index,
            type="video",
            url=video_url,
            thumbnail_url=thumb_url,
            width=width,
            height=height,
            duration_seconds=_as_float(
                _first(media, "video_duration", "duration")
            ),
        )

    image_url, width, height = _extract_image_url(media)

    return MediaItem(
        index=index,
        type="image",
        url=image_url,
        width=width,
        height=height,
    )


def _extract_carousel(media: dict[str, Any]) -> list[MediaItem]:
    # Current Instagram product payload.
    carousel = media.get("carousel_media")
    if isinstance(carousel, list) and carousel:
        return [
            _media_item(item, idx)
            for idx, item in enumerate(carousel)
            if isinstance(item, dict)
        ]

    # Legacy GraphQL sidecar.
    sidecar = media.get("edge_sidecar_to_children")
    if isinstance(sidecar, dict):
        edges = sidecar.get("edges")
        if isinstance(edges, list) and edges:
            out = []
            for idx, edge in enumerate(edges):
                if not isinstance(edge, dict):
                    continue
                node = edge.get("node")
                if isinstance(node, dict):
                    out.append(_media_item(node, idx))
            if out:
                return out

    return []


def normalize_media(
    media: dict[str, Any],
    *,
    shortcode: str,
    url: str,
    source: str,
) -> PostResult:
    carousel = _extract_carousel(media)

    if carousel:
        content_type = "carousel"
        media_items = carousel
    else:
        one = _media_item(media, 0)
        media_items = [one]
        content_type = one.type

    likes = _as_int(media.get("like_count"))
    comments = _as_int(media.get("comment_count"))

    # Legacy GraphQL counts.
    if likes is None:
        for key in ("edge_media_preview_like", "edge_liked_by"):
            value = media.get(key)
            if isinstance(value, dict):
                likes = _as_int(value.get("count"))
                if likes is not None:
                    break

    if comments is None:
        for key in (
            "edge_media_preview_comment",
            "edge_media_to_parent_comment",
            "edge_media_to_comment",
        ):
            value = media.get(key)
            if isinstance(value, dict):
                comments = _as_int(value.get("count"))
                if comments is not None:
                    break

    return PostResult(
        url=url,
        shortcode=shortcode,
        type=content_type,
        likes=likes,
        comments=comments,
        caption=_extract_caption(media),
        author=_extract_author(media),
        published_at=_as_int(
            _first(media, "taken_at", "taken_at_timestamp")
        ),
        media=media_items,
        source=source,
    )


def _find_media_in_response(payload: dict[str, Any]) -> dict[str, Any] | None:
    data = payload.get("data")
    if not isinstance(data, dict):
        return None

    polaris = data.get("xig_polaris_media")
    if isinstance(polaris, dict):
        product = polaris.get("if_not_gated_logged_out")
        if isinstance(product, dict):
            return product
        return polaris

    # Legacy response path.
    legacy = data.get("xdt_api__v1__media__shortcode__web_info")
    if isinstance(legacy, dict):
        items = legacy.get("items")
        if isinstance(items, list) and items and isinstance(items[0], dict):
            return items[0]

    return None


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def _find_media_in_html(page_html: str) -> dict[str, Any] | None:
    """
    Fallback for prefetched JSON embedded in <script data-sjs>.
    """
    scripts = re.findall(
        r"<script\b[^>]*\bdata-sjs[^>]*>(.*?)</script>",
        page_html,
        flags=re.S | re.I,
    )

    for raw in scripts:
        try:
            payload = json.loads(html_lib.unescape(raw))
        except Exception:
            continue

        for d in _walk(payload):
            polaris = d.get("xig_polaris_media")
            if isinstance(polaris, dict):
                product = polaris.get("if_not_gated_logged_out")
                if isinstance(product, dict):
                    return product
                return polaris

    return None


def get_post(
    url: str,
    *,
    timeout: float = 25.0,
    return_raw: bool = False,
):
    shortcode = extract_shortcode(url)
    canonical = canonical_url(url)
    media_id = shortcode_to_media_id(shortcode)

    session = _session()

    # 1) Anonymous Instagram homepage -> LSD + anonymous cookies.
    home = session.get(
        BASE + "/",
        headers=_headers(),
        timeout=timeout,
    )
    home.raise_for_status()

    lsd = _extract_lsd(home.text)

    # 2) Accessibility call; current yt-dlp uses this before GraphQL and
    # it usually causes Instagram to set csrftoken for the anonymous session.
    ruling = session.get(
        BASE + "/api/v1/web/get_ruling_for_content/",
        params={
            "content_type": "MEDIA",
            "target_id": media_id,
        },
        headers=_headers(canonical),
        timeout=timeout,
    )

    if ruling.status_code == 429:
        raise InstagramError("Instagram anonymous rate limit: HTTP 429")

    csrf = session.cookies.get("csrftoken")

    gql_headers = _headers(canonical)
    gql_headers.update(
        {
            "Content-Type": "application/x-www-form-urlencoded",
            "X-FB-Friendly-Name": GRAPHQL_FRIENDLY_NAME,
            "X-FB-LSD": lsd,
            "X-Requested-With": "XMLHttpRequest",
        }
    )

    if csrf:
        gql_headers["X-CSRFToken"] = csrf

    payload = {
        "lsd": lsd,
        "fb_api_caller_class": "RelayModern",
        "fb_api_req_friendly_name": GRAPHQL_FRIENDLY_NAME,
        "server_timestamps": "true",
        "variables": json.dumps(
            {"media_id": media_id},
            separators=(",", ":"),
        ),
        "doc_id": GRAPHQL_DOC_ID,
    }

    response = session.post(
        BASE + "/api/graphql",
        headers=gql_headers,
        data=payload,
        timeout=timeout,
    )

    raw = None

    if response.status_code == 429:
        raise InstagramError("Instagram anonymous rate limit: HTTP 429")

    if response.status_code == 200:
        try:
            raw = response.json()
        except Exception:
            raw = None

        if isinstance(raw, dict):
            media = _find_media_in_response(raw)
            if isinstance(media, dict):
                result = normalize_media(
                    media,
                    shortcode=shortcode,
                    url=canonical,
                    source="instagram-logged-out-graphql",
                )
                return (result, raw) if return_raw else result

    # 3) HTML fallback.
    page = session.get(
        canonical,
        headers=_headers(canonical),
        timeout=timeout,
        allow_redirects=True,
    )

    final_url = str(getattr(page, "url", ""))

    if "/accounts/login" in final_url:
        raise InstagramError(
            "Instagram отправил анонимный IP на login wall. "
            "Это rate-limit/IP restriction; попробуй другой IP или реже опрашивать."
        )

    media = _find_media_in_html(page.text)
    if isinstance(media, dict):
        result = normalize_media(
            media,
            shortcode=shortcode,
            url=canonical,
            source="instagram-embedded-json",
        )
        return (result, raw) if return_raw else result

    raise InstagramError(
        "Instagram не вернул публичные данные поста. "
        "Возможные причины: private/deleted post, rate limit или временное изменение web API."
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse public Instagram posts/carousels without Apify/login"
    )
    parser.add_argument("url", help="Instagram /p/ URL")
    parser.add_argument(
        "--raw",
        action="store_true",
        help="Добавить сырой GraphQL JSON в вывод",
    )
    args = parser.parse_args()

    try:
        if args.raw:
            result, raw = get_post(args.url, return_raw=True)
            output = {
                "normalized": result.to_dict(),
                "raw": raw,
            }
        else:
            output = get_post(args.url).to_dict()

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
