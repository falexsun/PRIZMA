#!/usr/bin/env python3
"""
Public MAX post parser through MXStat / Maxoteka — no MAX API token.

Input:
    https://max.ru/channel_name/POST_ID

Primary source:
    MXStat public channel page

Fallback:
    Maxoteka public archive

Returns when exposed by aggregators:
    views, comments, reactions, text/date.

Install:
    pip install requests beautifulsoup4

Usage:
    python max_public_parser.py \
      "https://max.ru/max_news/AZv5-eGoI5I"

Debug:
    python max_public_parser.py URL --save-html max_debug.html
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from typing import Any
from urllib.parse import urlparse, quote

import requests
from bs4 import BeautifulSoup, Tag


class MaxParseError(RuntimeError):
    pass


@dataclass
class MaxPost:
    platform: str
    input_url: str
    channel: str
    post_id: str
    text: str | None
    views: int | None
    comments: int | None
    reactions_total: int | None
    reactions: dict[str, int]
    reposts: int | None
    datetime: str | None
    source: str
    source_url: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def parse_count(value: str | int | None) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value

    s = str(value).strip().replace("\u00a0", " ")
    if not s:
        return None

    # Russian and English compact numbers.
    m = re.search(
        r"([\d.,]+)\s*(тыс\.?|млн|млрд|k|m|b)?",
        s,
        flags=re.I,
    )
    if not m:
        return None

    raw = m.group(1)
    suffix = (m.group(2) or "").lower().rstrip(".")

    if suffix:
        raw = raw.replace(",", ".")
        try:
            number = float(raw)
        except ValueError:
            return None

        if suffix in {"тыс", "k"}:
            return int(number * 1_000)
        if suffix in {"млн", "m"}:
            return int(number * 1_000_000)
        if suffix in {"млрд", "b"}:
            return int(number * 1_000_000_000)

    digits = re.sub(r"\D", "", raw)
    return int(digits) if digits else None


def parse_max_url(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    host = parsed.netloc.lower()

    if host not in {"max.ru", "www.max.ru"}:
        raise ValueError("Нужна ссылка max.ru/...")

    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        raise ValueError(
            "Нужна ссылка на конкретный пост MAX: https://max.ru/channel/POST_ID"
        )

    channel = parts[0].lstrip("@")
    post_id = parts[1]
    return channel, post_id


def _normalize_max_link(url: str) -> str:
    parsed = urlparse(url)
    return f"https://max.ru{parsed.path.rstrip('/')}"


def _find_post_container(soup: BeautifulSoup, input_url: str, post_id: str) -> Tag | None:
    target = _normalize_max_link(input_url)

    # Best case: aggregator contains an "Open in Max" anchor to exact post.
    for a in soup.find_all("a", href=True):
        href = a.get("href") or ""
        if href.startswith("//"):
            href = "https:" + href
        if href.startswith("/"):
            # Ignore aggregator-relative URLs.
            continue

        try:
            norm = _normalize_max_link(href)
        except Exception:
            norm = href

        if norm == target or post_id in href:
            # Walk upward to a sensible post-sized container.
            node: Tag | None = a
            best = None
            for _ in range(8):
                if not isinstance(node, Tag):
                    break
                text = node.get_text(" ", strip=True)
                if 30 <= len(text) <= 20_000:
                    best = node
                classes = " ".join(node.get("class", []))
                if re.search(r"post|publication|message|card|item", classes, re.I):
                    return node
                node = node.parent
            if best is not None:
                return best

    # Some public pages may put the post id in data-* attributes.
    for tag in soup.find_all(True):
        attrs = " ".join(str(v) for v in tag.attrs.values())
        if post_id in attrs:
            return tag

    return None


def _extract_comments(text: str) -> int | None:
    patterns = [
        r"Комментарии\s*\(([\d\s.,]+(?:\s*(?:тыс|млн))?)\)",
        r"Комментарии\s*[:\-]?\s*([\d\s.,]+(?:\s*(?:тыс|млн))?)",
        r"Comments\s*\(([\d\s.,]+(?:\s*[KMB])?)\)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            return parse_count(m.group(1))
    return None


def _extract_reactions(text: str) -> tuple[dict[str, int], int | None]:
    reactions: dict[str, int] = {}

    # Explicit emoji+count pairs: 👍48,75 тыс. ❤️25,01 тыс.
    pattern = re.compile(
        r"([👍❤️❤🔥👏😍🥰😁😂🎉🤡👎😢😡🤔🤩🙏💯🤝]+)"
        r"\s*([\d.,]+\s*(?:тыс\.?|млн|млрд|[KMB])?)",
        re.I,
    )

    for emoji, num in pattern.findall(text):
        count = parse_count(num)
        if count is not None:
            reactions[emoji] = max(reactions.get(emoji, 0), count)

    # MXStat often collapses the tail as "Еще 17,83 тыс."
    m = re.search(
        r"(?:Еще|Ещё|Other)\s+([\d.,]+\s*(?:тыс\.?|млн|млрд|[KMB])?)",
        text,
        re.I,
    )
    if m:
        count = parse_count(m.group(1))
        if count is not None:
            reactions["other"] = count

    total = sum(reactions.values()) if reactions else None
    return reactions, total


def _extract_views(text: str) -> int | None:
    # Explicit first.
    patterns = [
        r"([\d.,]+\s*(?:тыс\.?|млн|млрд|[KMB])?)\s*(?:просм\.?|просмотров|views?)",
        r"(?:Просмотры|Views)\s*[:\-]?\s*([\d.,]+\s*(?:тыс\.?|млн|млрд|[KMB])?)",
    ]
    for p in patterns:
        m = re.search(p, text, re.I)
        if m:
            value = parse_count(m.group(1))
            if value is not None:
                return value

    # MXStat cards often render "7,11 млн👍..." with no "views" word.
    m = re.search(
        r"(?:^|\n|\s)([\d.,]+\s*(?:тыс\.?|млн|млрд))"
        r"(?=\s*[👍❤️❤🔥👏😍🥰😁😂🎉🤡👎]|\s*ER\b|\s*ERR\b)",
        text,
        re.I,
    )
    if m:
        return parse_count(m.group(1))

    return None


def _extract_datetime(container: Tag, text: str) -> str | None:
    time_el = container.find("time")
    if time_el:
        return time_el.get("datetime") or time_el.get_text(" ", strip=True)

    # MXStat/Maxoteka current public dates.
    m = re.search(
        r"\b(\d{1,2}[.\s](?:\d{1,2}|янв\w*|фев\w*|мар\w*|апр\w*|ма[йя]|"
        r"июн\w*|июл\w*|авг\w*|сен\w*|окт\w*|ноя\w*|дек\w*)"
        r"[.\s]\d{4}(?:[,\s]+\d{1,2}:\d{2})?)",
        text,
        re.I,
    )
    return m.group(1) if m else None


def _clean_text(text: str) -> str | None:
    text = re.sub(r"\s+", " ", text).strip()

    # Remove common UI tails while keeping post body.
    for marker in (
        "💬 Комментарии",
        "Открыть в Max",
        "Посмотреть пост",
        "ER Реакции",
        "ERR Просмотры",
    ):
        pos = text.find(marker)
        if pos > 20:
            text = text[:pos].strip()

    return text or None


def parse_provider_html(
    html: str,
    input_url: str,
    *,
    provider: str,
    provider_url: str,
) -> MaxPost:
    channel, post_id = parse_max_url(input_url)
    soup = BeautifulSoup(html, "html.parser")

    container = _find_post_container(soup, input_url, post_id)

    if container is None:
        raise MaxParseError(
            f"{provider}: точный пост {post_id} не найден на странице канала"
        )

    full_text = container.get_text(" ", strip=True)

    views = _extract_views(full_text)
    comments = _extract_comments(full_text)
    reactions, reactions_total = _extract_reactions(full_text)

    reposts = None
    m = re.search(
        r"(?:Репосты|Reposts)\s*[:\-]?\s*([\d.,]+\s*(?:тыс\.?|млн|[KMB])?)",
        full_text,
        re.I,
    )
    if m:
        reposts = parse_count(m.group(1))

    return MaxPost(
        platform="max",
        input_url=input_url,
        channel=channel,
        post_id=post_id,
        text=_clean_text(full_text),
        views=views,
        comments=comments,
        reactions_total=reactions_total,
        reactions=reactions,
        reposts=reposts,
        datetime=_extract_datetime(container, full_text),
        source=provider,
        source_url=provider_url,
    )


def _provider_urls(channel: str) -> list[tuple[str, str]]:
    # mxstat.me often exposes individual post cards openly.
    return [
        ("mxstat.me", f"https://mxstat.me/channel/{quote('@' + channel, safe='')}"),
        ("mxstat.ru", f"https://mxstat.ru/channel/{quote(channel, safe='')}"),
        ("maxoteka", f"https://maxoteka.ru/channel/{quote(channel, safe='')}"),
    ]


def fetch_max_post(
    input_url: str,
    *,
    timeout: float = 25.0,
    session: requests.Session | None = None,
) -> tuple[MaxPost, dict[str, str]]:
    channel, _ = parse_max_url(input_url)

    own = session is None
    s = session or requests.Session()
    html_by_provider: dict[str, str] = {}
    errors: list[str] = []

    try:
        for provider, provider_url in _provider_urls(channel):
            try:
                response = s.get(
                    provider_url,
                    headers={
                        "User-Agent": (
                            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                            "AppleWebKit/537.36 (KHTML, like Gecko) "
                            "Chrome/140.0.0.0 Safari/537.36"
                        ),
                        "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
                    },
                    timeout=timeout,
                )

                if response.status_code != 200:
                    errors.append(f"{provider}: HTTP {response.status_code}")
                    continue

                html_by_provider[provider] = response.text

                try:
                    result = parse_provider_html(
                        response.text,
                        input_url,
                        provider=provider,
                        provider_url=provider_url,
                    )

                    # Prefer a result that actually has metrics.
                    if any(
                        value is not None
                        for value in (
                            result.views,
                            result.comments,
                            result.reactions_total,
                            result.reposts,
                        )
                    ):
                        return result, html_by_provider

                except Exception as exc:
                    errors.append(f"{provider}: {exc}")

            except requests.RequestException as exc:
                errors.append(f"{provider}: {exc}")

        raise MaxParseError(
            "Не удалось найти пост в публичных MAX-агрегаторах. "
            + " | ".join(errors)
        )
    finally:
        if own:
            s.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Parse a public MAX channel post without MAX API token"
    )
    parser.add_argument("url", help="https://max.ru/channel/POST_ID")
    parser.add_argument("--timeout", type=float, default=25.0)
    parser.add_argument(
        "--save-html",
        help="Prefix for saving provider HTML, e.g. max_debug",
    )
    args = parser.parse_args()

    try:
        result, htmls = fetch_max_post(args.url, timeout=args.timeout)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.save_html:
        for provider, html in htmls.items():
            safe = provider.replace(".", "_")
            with open(f"{args.save_html}_{safe}.html", "w", encoding="utf-8") as f:
                f.write(html)

    print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
