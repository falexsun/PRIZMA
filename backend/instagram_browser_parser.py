
from __future__ import annotations

import asyncio
import json
import re
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Response


@dataclass
class ReelMetrics:
    url: str
    shortcode: str
    username: str | None = None
    views: int | None = None
    plays: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    reposts: int | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_shortcode(url: str) -> str:
    parsed = urlparse(url)
    if "instagram.com" not in parsed.netloc.lower():
        raise ValueError("Not an Instagram URL")

    parts = [p for p in parsed.path.split("/") if p]
    for marker in ("reel", "reels", "p", "tv"):
        if marker in parts:
            i = parts.index(marker)
            if i + 1 < len(parts):
                return parts[i + 1]
    raise ValueError("Cannot find Instagram shortcode")


def _int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str):
        s = value.strip().replace(",", "").replace(" ", "")
        m = re.fullmatch(r"([\d.]+)([KMB])?", s, re.I)
        if not m:
            return None
        n = float(m.group(1))
        mul = {"K": 1_000, "M": 1_000_000, "B": 1_000_000_000}.get(
            (m.group(2) or "").upper(), 1
        )
        return int(n * mul)
    return None


COUNT_ALIASES = {
    "views": (
        "view_count", "video_view_count", "views_count",
        "ig_play_count",
    ),
    "plays": (
        "play_count", "video_play_count", "plays_count",
    ),
    "likes": (
        "like_count", "likes_count",
    ),
    "comments": (
        "comment_count", "comments_count",
    ),
    "shares": (
        "share_count", "shares_count", "reshare_count",
    ),
    "saves": (
        "save_count", "saved_count", "saves_count",
    ),
    "reposts": (
        "repost_count", "reposts_count",
    ),
}


def _first(d: dict[str, Any], names: tuple[str, ...]) -> Any:
    for name in names:
        if name in d and d[name] is not None:
            return d[name]
    return None


def _username(d: dict[str, Any]) -> str | None:
    for key in ("user", "owner"):
        value = d.get(key)
        if isinstance(value, dict):
            username = value.get("username")
            if isinstance(username, str):
                return username
    username = d.get("username")
    return username if isinstance(username, str) else None


def _shortcode(d: dict[str, Any]) -> str | None:
    for key in ("code", "shortcode"):
        value = d.get(key)
        if isinstance(value, str):
            return value
    return None


def _candidate_score(d: dict[str, Any], shortcode: str) -> int:
    score = 0

    code = _shortcode(d)
    if code == shortcode:
        score += 100
    elif code:
        score -= 20

    if d.get("product_type") in ("clips", "reel"):
        score += 10

    if d.get("__typename") == "GraphVideo":
        score += 5

    for aliases in COUNT_ALIASES.values():
        if _first(d, aliases) is not None:
            score += 3

    if isinstance(d.get("video_versions"), list):
        score += 3

    if isinstance(d.get("user"), dict) or isinstance(d.get("owner"), dict):
        score += 2

    return score


def _walk(obj: Any):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from _walk(value)


def find_best_media(payloads: list[Any], shortcode: str) -> dict[str, Any] | None:
    best = None
    best_score = 0

    for payload in payloads:
        for d in _walk(payload):
            score = _candidate_score(d, shortcode)
            if score > best_score:
                best_score = score
                best = d

    # Не принимаем случайный объект только потому, что там есть один count.
    return best if best_score >= 6 else None


def metrics_from_media(
    media: dict[str, Any],
    url: str,
    shortcode: str,
    source: str,
) -> ReelMetrics:
    values = {
        field: _int(_first(media, aliases))
        for field, aliases in COUNT_ALIASES.items()
    }

    # У Instagram в разных web-ответах "views" может называться play_count.
    if values["views"] is None and values["plays"] is not None:
        values["views"] = values["plays"]

    return ReelMetrics(
        url=url,
        shortcode=shortcode,
        username=_username(media),
        source=source,
        **values,
    )


def metrics_from_meta_description(
    text: str,
    url: str,
    shortcode: str,
) -> ReelMetrics:
    """
    Instagram meta description часто содержит:
      "10K likes, 120 comments - username on ..."
    Это fallback; views там обычно нет.
    """
    likes = comments = None

    m = re.search(r"([\d.,]+[KMB]?)\s+likes?", text, re.I)
    if m:
        likes = _int(m.group(1))

    m = re.search(r"([\d.,]+[KMB]?)\s+comments?", text, re.I)
    if m:
        comments = _int(m.group(1))

    return ReelMetrics(
        url=url,
        shortcode=shortcode,
        likes=likes,
        comments=comments,
        source="meta-description",
    )


async def get_reel_metrics(
    url: str,
    *,
    headless: bool = True,
    proxy_server: str | None = None,
    proxy_username: str | None = None,
    proxy_password: str | None = None,
    timeout_ms: int = 45_000,
) -> ReelMetrics:
    """
    Без Instagram login, cookies пользователя и API token.

    Идея:
    1. настоящий Chromium открывает публичный Reel;
    2. браузер сам получает Instagram cookies/CSRF/LSD/doc_id;
    3. мы слушаем JSON/XHR ответы страницы;
    4. если network JSON не содержит metrics — читаем embedded JSON из <script>;
    5. последний fallback — meta description.

    Для сервера обычно лучше:
        xvfb-run -a python instagram_browser_parser.py URL
    и headless=False, если Instagram режет headless IP/браузер.
    """
    shortcode = extract_shortcode(url)
    canonical = f"https://www.instagram.com/reel/{shortcode}/"

    proxy = None
    if proxy_server:
        proxy = {"server": proxy_server}
        if proxy_username:
            proxy["username"] = proxy_username
        if proxy_password:
            proxy["password"] = proxy_password

    captured: list[Any] = []

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=headless,
            proxy=proxy,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-default-browser-check",
                "--disable-dev-shm-usage",
            ],
        )

        context = await browser.new_context(
            locale="en-US",
            timezone_id="Europe/Amsterdam",
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

        async def inspect_response(response: Response):
            # Нас интересуют GraphQL / API JSON ответы Instagram.
            url_l = response.url.lower()
            if not any(x in url_l for x in (
                "/api/graphql",
                "/graphql/query",
                "/api/v1/",
            )):
                return

            content_type = (await response.all_headers()).get("content-type", "")
            if "json" not in content_type and "graphql" not in url_l:
                return

            try:
                captured.append(await response.json())
            except Exception:
                pass

        page.on("response", inspect_response)

        try:
            await page.goto(
                canonical,
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )

            # Дать странице догрузить XHR/GraphQL.
            await page.wait_for_timeout(4500)

            # Иногда network request начинается после небольшого scroll.
            await page.mouse.wheel(0, 500)
            await page.wait_for_timeout(1500)

            # 1. network JSON
            media = find_best_media(captured, shortcode)
            if media:
                result = metrics_from_media(
                    media, canonical, shortcode, "browser-network-json"
                )
                if any(
                    getattr(result, field) is not None
                    for field in ("views", "likes", "comments")
                ):
                    return result

            # 2. embedded JSON внутри script-тегов.
            scripts = await page.locator("script").all_text_contents()
            embedded_payloads = []
            for raw in scripts:
                raw = raw.strip()
                if not raw or len(raw) < 2:
                    continue
                if raw[0] not in "[{":
                    continue
                try:
                    embedded_payloads.append(json.loads(raw))
                except Exception:
                    pass

            media = find_best_media(embedded_payloads, shortcode)
            if media:
                result = metrics_from_media(
                    media, canonical, shortcode, "browser-embedded-json"
                )
                if any(
                    getattr(result, field) is not None
                    for field in ("views", "likes", "comments")
                ):
                    return result

            # 3. meta description.
            meta = page.locator('meta[name="description"]')
            if await meta.count():
                content = await meta.first.get_attribute("content")
                if content:
                    result = metrics_from_meta_description(
                        content, canonical, shortcode
                    )
                    if result.likes is not None or result.comments is not None:
                        return result

            # Если дошли сюда — проверим, не упёрлись ли в login wall.
            final_url = page.url
            body = (await page.locator("body").inner_text())[:5000].lower()

            if "/accounts/login" in final_url or "log in" in body:
                raise RuntimeError(
                    "Instagram показал login wall. "
                    "Для стабильной работы нужен другой/резидентский IP "
                    "или меньшая частота запросов."
                )

            raise RuntimeError(
                "Reel opened, but public page did not expose counters."
            )
        finally:
            await context.close()
            await browser.close()


async def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--proxy")
    parser.add_argument("--proxy-user")
    parser.add_argument("--proxy-password")
    args = parser.parse_args()

    result = await get_reel_metrics(
        args.url,
        headless=not args.headed,
        proxy_server=args.proxy,
        proxy_username=args.proxy_user,
        proxy_password=args.proxy_password,
    )
    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
