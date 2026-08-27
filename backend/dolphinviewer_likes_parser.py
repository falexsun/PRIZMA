#!/usr/bin/env python3
"""
DolphinViewer Instagram Likes parser / API sniffer.

Goal:
    Instagram /p/ URL -> DolphinViewer -> exact like count
    without Instagram login or Apify.

The script:
1) opens DolphinViewer Likes Viewer;
2) inserts an Instagram post/carousel URL;
3) intercepts XHR/fetch requests and JSON responses;
4) extracts like_count from JSON when possible;
5) falls back to the rendered DOM;
6) with --debug prints the internal DolphinViewer endpoint/payload so it
   can later be replaced with a direct requests/httpx client.

Install:
    pip install playwright
    playwright install chromium

Usage:
    python dolphinviewer_likes_parser.py \
      "https://www.instagram.com/p/SHORTCODE/"

Debug internal API:
    python dolphinviewer_likes_parser.py URL --debug

Visible browser:
    python dolphinviewer_likes_parser.py URL --headed

Proxy:
    python dolphinviewer_likes_parser.py URL \
      --proxy http://host:port \
      --proxy-user USER \
      --proxy-password PASS
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
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Page, Request, Response


DOLPHIN_URL = "https://dolphinviewer.net/en/instagram-likes-viewer/"


class DolphinError(RuntimeError):
    pass


@dataclass
class LikesResult:
    post_url: str
    source: str = "dolphinviewer"
    likes: int | None = None
    liker_count_visible: int | None = None
    extraction_source: str | None = None
    backend_url: str | None = None
    backend_method: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_instagram_post_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if not (
        host == "instagram.com"
        or host.endswith(".instagram.com")
        or host == "instagr.am"
        or host.endswith(".instagr.am")
    ):
        raise ValueError("Нужна ссылка Instagram")

    m = re.search(r"/(p|reel|reels)/([A-Za-z0-9_-]+)", parsed.path)
    if not m:
        raise ValueError(
            "Нужна ссылка вида https://www.instagram.com/p/SHORTCODE/ "
            "или /reel/SHORTCODE/"
        )

    kind, shortcode = m.groups()
    canonical_kind = "reel" if kind in {"reel", "reels"} else "p"
    return f"https://www.instagram.com/{canonical_kind}/{shortcode}/"


def to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        return int(value)

    s = str(value).strip()
    if not s or s.lower() in {"none", "null", "n/a", "-", "—"}:
        return None

    # Common forms: 12,345 / 12.3K / 1.2M
    m = re.search(r"([\d.,]+)\s*([KMB])?", s, flags=re.I)
    if not m:
        return None

    raw = m.group(1)
    suffix = (m.group(2) or "").upper()

    if suffix:
        raw = raw.replace(",", "")
        try:
            number = float(raw)
        except ValueError:
            return None
        mult = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}[suffix]
        return int(number * mult)

    # Without suffix, commas/dots in UI are usually thousands separators.
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


LIKE_KEYS = (
    "like_count",
    "likeCount",
    "likes_count",
    "likesCount",
    "likes",
    "total_likes",
    "totalLikes",
    "total_count",
    "totalCount",
    "count",
)

LIKERS_KEYS = (
    "likers",
    "users",
    "accounts",
    "items",
    "results",
    "data",
)


def extract_like_count_from_json(payload: Any) -> int | None:
    """
    Tries several common result shapes.

    Important: generic `count` is accepted only when the surrounding object
    looks likes-related, to avoid picking arbitrary counts.
    """
    best: tuple[int, int] | None = None  # (score, value)

    for d in _walk(payload):
        key_text = " ".join(map(str, d.keys())).lower()
        blob_hint = (
            "like" in key_text
            or any("like" in str(v).lower() for v in list(d.values())[:8]
                   if isinstance(v, str))
        )

        for key in LIKE_KEYS:
            if key not in d:
                continue

            value = to_int(d.get(key))
            if value is None:
                continue

            score = 1

            if "like" in key.lower():
                score += 10
            if blob_hint:
                score += 5
            if key.lower() in {"total_count", "totalcount", "count"} and not blob_hint:
                score -= 5

            if best is None or score > best[0]:
                best = (score, value)

    return best[1] if best and best[0] > 0 else None


def count_visible_likers_from_json(payload: Any) -> int | None:
    """
    Counts visible liker records when DolphinViewer returns a capped list.
    This is NOT used as total likes; it's diagnostic only.
    """
    best = 0

    for d in _walk(payload):
        for key in LIKERS_KEYS:
            value = d.get(key)
            if not isinstance(value, list):
                continue

            plausible = 0
            for item in value:
                if not isinstance(item, dict):
                    continue
                keys = {k.lower() for k in item}
                if {"username", "user_name", "profile_pic_url", "full_name"} & keys:
                    plausible += 1

            best = max(best, plausible)

    return best or None


def extract_like_count_from_text(text: str) -> int | None:
    patterns = (
        r"(?:total\s+)?likes?\s*[:\n\r\t ]+\s*([\d.,]+\s*[KMB]?)",
        r"([\d.,]+\s*[KMB]?)\s+(?:total\s+)?likes?\b",
        r"liked\s+by\s+([\d.,]+\s*[KMB]?)",
    )

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.I)
        if m:
            value = to_int(m.group(1))
            if value is not None:
                return value

    return None


def looks_like_backend_request(url: str, resource_type: str) -> bool:
    low = url.lower()
    if "dolphinviewer.net" not in low:
        return False

    if resource_type in {"xhr", "fetch"}:
        return True

    return any(
        token in low
        for token in (
            "/api/",
            "ajax",
            "like",
            "instagram",
            "lookup",
            "search",
            "post",
        )
    )


async def find_input(page: Page):
    candidates = [
        'input[type="url"]',
        'input[placeholder*="instagram" i]',
        'input[placeholder*="username" i]',
        'input[placeholder*="link" i]',
        'input[type="text"]',
    ]

    for selector in candidates:
        loc = page.locator(selector)
        for i in range(await loc.count()):
            el = loc.nth(i)
            try:
                if await el.is_visible():
                    return el
            except Exception:
                pass

    raise DolphinError("Не найдено поле @username or link")


async def submit_lookup(page: Page, input_box):
    candidates = [
        page.get_by_role("button", name=re.compile(r"view\s+likes", re.I)),
        page.get_by_role("button", name=re.compile(r"search", re.I)),
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

    await input_box.press("Enter")


async def scrape_dolphinviewer(
    post_url: str,
    *,
    headless: bool = True,
    timeout_ms: int = 60_000,
    debug: bool = False,
    proxy_server: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
) -> LikesResult:
    canonical = validate_instagram_post_url(post_url)

    requests_seen: list[dict[str, Any]] = []
    json_responses: list[dict[str, Any]] = []

    proxy = None
    if proxy_server:
        proxy = {"server": proxy_server}
        if proxy_username:
            proxy["username"] = proxy_username
        if proxy_password:
            proxy["password"] = proxy_password

    async with async_playwright() as p:
        launch_kwargs: dict[str, Any] = {
            "headless": headless,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        }

        if proxy:
            launch_kwargs["proxy"] = proxy

        if os.path.exists("/usr/bin/chromium"):
            launch_kwargs["executable_path"] = "/usr/bin/chromium"

        browser = await p.chromium.launch(**launch_kwargs)

        context = await browser.new_context(
            locale="en-US",
            viewport={"width": 1365, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": "en-US,en;q=0.9",
            },
        )

        page = await context.new_page()

        def on_request(request: Request):
            if not looks_like_backend_request(request.url, request.resource_type):
                return

            item: dict[str, Any] = {
                "method": request.method,
                "url": request.url,
                "resource_type": request.resource_type,
            }

            try:
                item["post_data"] = request.post_data
            except Exception:
                pass

            requests_seen.append(item)

        async def on_response(response: Response):
            request = response.request

            if not looks_like_backend_request(
                response.url,
                request.resource_type,
            ):
                return

            try:
                headers = await response.all_headers()
            except Exception:
                headers = {}

            content_type = headers.get("content-type", "").lower()

            record: dict[str, Any] = {
                "url": response.url,
                "status": response.status,
                "method": request.method,
                "resource_type": request.resource_type,
                "content_type": content_type,
            }

            if "json" in content_type:
                try:
                    payload = await response.json()
                    record["json"] = payload
                    json_responses.append(record)
                except Exception:
                    pass

        page.on("request", on_request)
        page.on("response", on_response)

        try:
            await page.goto(
                DOLPHIN_URL,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            input_box = await find_input(page)
            await input_box.fill(canonical)
            await submit_lookup(page, input_box)

            deadline = asyncio.get_running_loop().time() + timeout_ms / 1000

            best_likes = None
            best_visible_likers = None
            backend_url = None
            backend_method = None
            extraction_source = None

            while asyncio.get_running_loop().time() < deadline:
                # Prefer backend JSON.
                for record in reversed(json_responses):
                    payload = record.get("json")

                    likes = extract_like_count_from_json(payload)
                    visible = count_visible_likers_from_json(payload)

                    if likes is not None:
                        best_likes = likes
                        best_visible_likers = visible
                        backend_url = record["url"]
                        backend_method = record["method"]
                        extraction_source = "network-json"
                        break

                if best_likes is not None:
                    break

                # DOM fallback.
                body = await page.locator("body").inner_text()
                likes = extract_like_count_from_text(body)

                if likes is not None:
                    best_likes = likes
                    extraction_source = "dom"
                    break

                await page.wait_for_timeout(750)

            if debug:
                # Remove duplicate request entries while keeping useful fields.
                unique_requests = []
                seen = set()
                for item in requests_seen:
                    key = (
                        item.get("method"),
                        item.get("url"),
                        item.get("post_data"),
                    )
                    if key not in seen:
                        seen.add(key)
                        unique_requests.append(item)

                debug_output = {
                    "page_url": page.url,
                    "input_url": canonical,
                    "backend_requests": unique_requests,
                    "json_response_endpoints": [
                        {
                            "method": r["method"],
                            "status": r["status"],
                            "url": r["url"],
                            "content_type": r["content_type"],
                        }
                        for r in json_responses
                    ],
                }

                print(
                    "=== DOLPHINVIEWER API DEBUG ===",
                    file=sys.stderr,
                )
                print(
                    json.dumps(debug_output, ensure_ascii=False, indent=2),
                    file=sys.stderr,
                )

            if best_likes is None:
                page_text = (await page.locator("body").inner_text())[:3000]
                lower = page_text.lower()

                if any(
                    x in lower
                    for x in (
                        "private account",
                        "private post",
                        "post not found",
                        "invalid url",
                    )
                ):
                    raise DolphinError(
                        "DolphinViewer не смог открыть этот пост "
                        "(private/deleted/invalid)."
                    )

                raise DolphinError(
                    "DolphinViewer загрузился, но like count не найден. "
                    "Запусти с --debug: внутренний endpoint может вернуть "
                    "не-JSON или сайт мог изменить формат."
                )

            return LikesResult(
                post_url=canonical,
                likes=best_likes,
                liker_count_visible=best_visible_likers,
                extraction_source=extraction_source,
                backend_url=backend_url,
                backend_method=backend_method,
            )

        finally:
            await context.close()
            await browser.close()


async def main() -> int:
    parser = argparse.ArgumentParser(
        description="Get Instagram post/carousel likes through DolphinViewer"
    )

    parser.add_argument("url", help="Instagram /p/ or /reel/ URL")
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Запустить видимый Chromium",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Показать внутренние XHR/fetch DolphinViewer",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60,
        help="Timeout, seconds (default: 60)",
    )

    parser.add_argument("--proxy", help="Proxy server, e.g. http://host:port")
    parser.add_argument("--proxy-user")
    parser.add_argument("--proxy-password")

    args = parser.parse_args()

    try:
        result = await scrape_dolphinviewer(
            args.url,
            headless=not args.headed,
            timeout_ms=args.timeout * 1000,
            debug=args.debug,
            proxy_server=args.proxy,
            proxy_username=args.proxy_user,
            proxy_password=args.proxy_password,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
