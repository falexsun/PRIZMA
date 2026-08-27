#!/usr/bin/env python3
"""
Public Telegram post parser — no API key, no login, no Telethon.

Input:
    https://t.me/channel_name/123
    https://t.me/s/channel_name/123
    https://telegram.me/channel_name/123

Data source:
    server-rendered Telegram public preview: https://t.me/s/<channel>

Returns:
    views, reactions (with emoji breakdown), comments/replies when visible,
    text, date, author/channel and media URLs when present.

Install:
    pip install requests beautifulsoup4

Usage:
    python telegram_public_parser.py "https://t.me/durov/123"

Raw HTML debug:
    python telegram_public_parser.py URL --save-html telegram.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup, Tag


class TelegramParseError(RuntimeError):
    pass


@dataclass
class TelegramPost:
    platform: str
    input_url: str
    channel: str
    message_id: int
    text: str | None
    views: int | None
    comments: int | None
    reactions_total: int | None
    reactions: dict[str, int]
    author: str | None
    datetime: str | None
    media_urls: list[str]
    source: str = "telegram-web-preview"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_count(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value

    s = str(value).strip().replace("\u00a0", "").replace(" ", "")
    if not s:
        return None

    m = re.search(r"([\d.,]+)\s*([KMBКММЛНТЫС]*)", s, re.I)
    if not m:
        return None

    raw = m.group(1)
    suffix = (m.group(2) or "").lower()

    # Decimal suffix forms: 12.6M, 7.03K.
    if suffix:
        raw = raw.replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            return None

        if suffix in {"k", "к", "тыс"}:
            return int(number * 1_000)
        if suffix in {"m", "м", "млн"}:
            return int(number * 1_000_000)
        if suffix in {"b", "млрд"}:
            return int(number * 1_000_000_000)

    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def parse_post_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        raise ValueError("Нужна публичная ссылка t.me/...")

    parts = [p for p in parsed.path.split("/") if p]

    if parts and parts[0] == "s":
        parts = parts[1:]

    if len(parts) < 2:
        raise ValueError("Нужна ссылка на конкретный пост: https://t.me/channel/123")

    channel = parts[0].lstrip("@")
    try:
        message_id = int(parts[1])
    except ValueError as exc:
        raise ValueError("Не найден числовой message_id в Telegram URL") from exc

    return channel, message_id


def _style_background_url(style: str | None) -> str | None:
    if not style:
        return None
    m = re.search(r"url\(['\"]?([^'\")]+)", style)
    return m.group(1) if m else None


def _extract_media(block: Tag) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()

    def add(url: str | None):
        if not url:
            return
        url = url.strip()
        if url.startswith("//"):
            url = "https:" + url
        if url.startswith("http") and url not in seen:
            seen.add(url)
            result.append(url)

    # Photos are usually CSS background-image on <a>.
    for element in block.select("[style*='background-image']"):
        add(_style_background_url(element.get("style")))

    # Video/audio/source tags.
    for element in block.select("video, audio, source, img"):
        add(element.get("src"))
        add(element.get("poster"))

    return result


def _extract_reactions(block: Tag) -> tuple[dict[str, int], int | None]:
    reactions: dict[str, int] = {}

    # Current Telegram preview uses reaction buttons/items.
    candidates = block.select(
        ".tgme_widget_message_reaction, "
        ".tgme_widget_message_reaction_wrap, "
        "[class*='reaction']"
    )

    for element in candidates:
        text = " ".join(element.stripped_strings).strip()
        if not text:
            continue

        # Prefer explicit emoji spans if available.
        emoji_el = element.select_one(
            ".tgme_widget_message_reaction_emoji, "
            "[class*='reaction_emoji'], "
            "i"
        )
        count_el = element.select_one(
            ".tgme_widget_message_reaction_count, "
            "[class*='reaction_count']"
        )

        emoji = emoji_el.get_text(" ", strip=True) if emoji_el else None
        count_text = count_el.get_text(" ", strip=True) if count_el else None

        if emoji and count_text:
            count = parse_count(count_text)
            if count is not None:
                reactions[emoji] = max(reactions.get(emoji, 0), count)
                continue

        # Robust fallback for compact text such as "👍629" or "629👍".
        matches = re.findall(
            r"([^\w\s\d.,KMBКМ]+)\s*([\d.,]+\s*[KMBКМ]?)"
            r"|([\d.,]+\s*[KMBКМ]?)\s*([^\w\s\d.,KMBКМ]+)",
            text,
            flags=re.I,
        )
        for a, b, c, d in matches:
            emoji, num = (a, b) if a and b else (d, c)
            emoji = emoji.strip()
            count = parse_count(num)
            if emoji and count is not None:
                reactions[emoji] = max(reactions.get(emoji, 0), count)

    total = sum(reactions.values()) if reactions else None
    return reactions, total


def _extract_comments(block: Tag) -> int | None:
    # Telegram calls comments "replies" in preview HTML.
    selectors = [
        ".tgme_widget_message_replies",
        ".tgme_widget_message_replies_count",
        "[class*='replies']",
        "[class*='comments']",
    ]

    for selector in selectors:
        for el in block.select(selector):
            count = parse_count(el.get_text(" ", strip=True))
            if count is not None:
                return count

    return None


def parse_post_html(html: str, input_url: str) -> TelegramPost:
    channel, message_id = parse_post_url(input_url)

    soup = BeautifulSoup(html, "html.parser")
    wanted = f"{channel}/{message_id}"

    block = soup.select_one(f'[data-post="{wanted}"]')

    # Case-insensitive channel mismatch / redirects.
    if block is None:
        for candidate in soup.select("[data-post]"):
            data_post = (candidate.get("data-post") or "").strip()
            if data_post.lower() == wanted.lower():
                block = candidate
                break

    if block is None:
        raise TelegramParseError(
            f"Пост {wanted} не найден в public preview. "
            "Возможно, канал приватный, пост удалён или Telegram не отдал его в окне preview."
        )

    text_el = block.select_one(".tgme_widget_message_text")
    text = text_el.get_text("\n", strip=True) if text_el else None

    views_el = block.select_one(".tgme_widget_message_views")
    views = parse_count(views_el.get_text(" ", strip=True)) if views_el else None

    comments = _extract_comments(block)
    reactions, reactions_total = _extract_reactions(block)

    author_el = block.select_one(
        ".tgme_widget_message_author_name, "
        ".tgme_widget_message_owner_name"
    )
    author = author_el.get_text(" ", strip=True) if author_el else None

    time_el = block.select_one("time[datetime]")
    dt = time_el.get("datetime") if time_el else None

    return TelegramPost(
        platform="telegram",
        input_url=input_url,
        channel=channel,
        message_id=message_id,
        text=text,
        views=views,
        comments=comments,
        reactions_total=reactions_total,
        reactions=reactions,
        author=author,
        datetime=dt,
        media_urls=_extract_media(block),
    )


def fetch_post(
    input_url: str,
    *,
    timeout: float = 20.0,
    session: requests.Session | None = None,
) -> tuple[TelegramPost, str]:
    channel, message_id = parse_post_url(input_url)

    # ?before=<id+1> strongly biases the preview window toward our post.
    preview_url = f"https://t.me/s/{channel}?before={message_id + 1}"

    own = session is None
    s = session or requests.Session()

    try:
        response = s.get(
            preview_url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/140.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
        )
        response.raise_for_status()

        return parse_post_html(response.text, input_url), response.text
    finally:
        if own:
            s.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse a public Telegram channel post without API/login"
    )
    parser.add_argument("url", help="https://t.me/channel/123")
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--save-html", help="Save Telegram preview HTML for debugging")
    args = parser.parse_args()

    try:
        result, html = fetch_post(args.url, timeout=args.timeout)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.save_html:
        with open(args.save_html, "w", encoding="utf-8") as f:
            f.write(html)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
