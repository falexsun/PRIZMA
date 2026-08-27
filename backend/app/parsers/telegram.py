import re
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError
from app.services.hashtag_extractor import extract_hashtags


def _parse_count(value: str | int | None) -> int:
    if value is None:
        return 0
    if isinstance(value, int):
        return value
    text = str(value).strip().replace("\xa0", "").replace(" ", "")
    if not text:
        return 0
    match = re.search(r"([\d.,]+)\s*([KMBКМ]|тыс|млн|млрд)?", text, re.IGNORECASE)
    if not match:
        return 0
    raw = match.group(1)
    suffix = (match.group(2) or "").lower()
    if suffix:
        try:
            number = float(raw.replace(",", "."))
        except ValueError:
            return 0
        if suffix in {"k", "к", "тыс"}:
            return int(number * 1_000)
        if suffix in {"m", "м", "млн"}:
            return int(number * 1_000_000)
        if suffix in {"b", "млрд"}:
            return int(number * 1_000_000_000)
    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else 0


def _channel_and_msg_id(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    if parsed.netloc.lower() not in {"t.me", "telegram.me", "www.t.me", "www.telegram.me"}:
        raise ParserNotFoundError(f"Cannot parse Telegram post host from {url}")
    parts = [part for part in parsed.path.split("/") if part]
    if parts and parts[0] == "s":
        parts = parts[1:]
    if len(parts) < 2:
        raise ParserNotFoundError(f"Cannot parse Telegram post path from {url}")
    try:
        return parts[0].lstrip("@"), int(parts[1])
    except ValueError as exc:
        raise ParserNotFoundError(f"Cannot parse Telegram message id from {url}") from exc


def _extract_comments(block: Tag) -> int:
    for selector in (
        ".tgme_widget_message_replies",
        ".tgme_widget_message_replies_count",
        "[class*='replies']",
        "[class*='comments']",
    ):
        for element in block.select(selector):
            count = _parse_count(element.get_text(" ", strip=True))
            if count:
                return count
    return 0


def _extract_reactions(block: Tag) -> int:
    counts = [
        _parse_count(element.get_text(" ", strip=True))
        for element in block.select(".tgme_widget_message_reaction_count, [class*='reaction_count']")
    ]
    if counts:
        return sum(counts)

    total = 0
    for element in block.select(".tgme_widget_message_reaction, [class*='reaction']"):
        text = element.get_text(" ", strip=True)
        matches = re.findall(
            r"([^\w\s\d.,KMBКМ]+)\s*([\d.,]+\s*(?:[KMBКМ]|тыс|млн)?)"
            r"|([\d.,]+\s*(?:[KMBКМ]|тыс|млн)?)\s*([^\w\s\d.,KMBКМ]+)",
            text,
            flags=re.IGNORECASE,
        )
        for left_emoji, left_count, right_count, right_emoji in matches:
            if left_emoji or right_emoji:
                total += _parse_count(left_count or right_count)
    return total


async def fetch(url: str) -> Metrics:
    channel, msg_id = _channel_and_msg_id(url)
    preview_url = f"https://t.me/s/{channel}?before={msg_id + 1}"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True) as client:
            response = await client.get(
                preview_url,
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
                    ),
                    "Accept-Language": "en-US,en;q=0.9",
                },
            )
    except httpx.HTTPError as exc:
        raise ParserUnavailableError(f"Telegram public preview request failed: {exc}") from exc

    if response.status_code == 404:
        raise ParserNotFoundError(f"Telegram post not found: {channel}/{msg_id}")
    if response.status_code != 200:
        raise ParserUnavailableError(f"Telegram returned status {response.status_code}")

    soup = BeautifulSoup(response.text, "html.parser")
    wanted = f"{channel}/{msg_id}"
    block = soup.select_one(f'[data-post="{wanted}"]')
    if block is None:
        for candidate in soup.select("[data-post]"):
            if (candidate.get("data-post") or "").lower() == wanted.lower():
                block = candidate
                break
    if block is None:
        raise ParserNotFoundError(f"Telegram post not found in public preview: {channel}/{msg_id}")

    views_el = block.select_one(".tgme_widget_message_views")
    text_el = block.select_one(".tgme_widget_message_text")
    text = text_el.get_text("\n", strip=True) if text_el else ""
    return Metrics(
        likes=_extract_reactions(block),
        reposts=0,
        comments=_extract_comments(block),
        saves=0,
        views=_parse_count(views_el.get_text(" ", strip=True) if views_el else None),
        hashtags=extract_hashtags(text),
    )
