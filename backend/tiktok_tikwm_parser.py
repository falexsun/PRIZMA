#!/usr/bin/env python3
"""
TikTok parser through TikWM (no API key, no Playwright, no TikTok login).

TikWM endpoint:
    https://www.tikwm.com/api/

Input:
    public TikTok video URL, short URL (vm.tiktok.com / vt.tiktok.com),
    or TikTok video ID.

Returns:
    views, likes, comments, shares, saves, downloads + metadata.

Install:
    pip install requests

Usage:
    python tiktok_tikwm_parser.py \
      "https://www.tiktok.com/@username/video/1234567890123456789"

Raw response:
    python tiktok_tikwm_parser.py URL --raw
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass, asdict
from typing import Any

import requests


API_URL = "https://www.tikwm.com/api/"


class TikWMError(RuntimeError):
    pass


@dataclass
class TikTokMetrics:
    platform: str
    input_url: str
    video_id: str | None
    author: str | None
    author_nickname: str | None
    title: str | None
    region: str | None
    duration_seconds: int | None

    views: int | None
    likes: int | None
    comments: int | None
    shares: int | None
    saves: int | None
    downloads: int | None

    created_at: int | None

    video_url: str | None
    video_url_hd: str | None
    cover_url: str | None

    images: list[str] | None

    source: str = "tikwm"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _to_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None

    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _absolute_tikwm_url(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None

    if value.startswith("//"):
        return "https:" + value

    if value.startswith("/"):
        return "https://www.tikwm.com" + value

    return value


def normalize(data: dict[str, Any], input_url: str) -> TikTokMetrics:
    author = data.get("author")
    if not isinstance(author, dict):
        author = {}

    images = data.get("images")
    if not isinstance(images, list):
        images = None
    else:
        images = [
            _absolute_tikwm_url(x)
            for x in images
            if isinstance(x, str) and x
        ]

    return TikTokMetrics(
        platform="tiktok",
        input_url=input_url,
        video_id=(
            str(data.get("id"))
            if data.get("id") is not None
            else (
                str(data.get("video_id"))
                if data.get("video_id") is not None
                else None
            )
        ),
        author=author.get("unique_id"),
        author_nickname=author.get("nickname"),
        title=data.get("title"),
        region=data.get("region"),
        duration_seconds=_to_int(data.get("duration")),

        # TikWM / TikTok native stat fields.
        views=_to_int(data.get("play_count")),
        likes=_to_int(data.get("digg_count")),
        comments=_to_int(data.get("comment_count")),
        shares=_to_int(data.get("share_count")),
        saves=_to_int(data.get("collect_count")),
        downloads=_to_int(data.get("download_count")),

        created_at=_to_int(data.get("create_time")),

        # SD/no-watermark and HD URLs when exposed.
        video_url=_absolute_tikwm_url(data.get("play")),
        video_url_hd=_absolute_tikwm_url(data.get("hdplay")),
        cover_url=_absolute_tikwm_url(
            data.get("cover") or data.get("origin_cover")
        ),

        # TikTok photo posts may contain images[] instead of video.
        images=images,
    )


def _request_once(
    input_url: str,
    *,
    hd: bool,
    timeout: float,
    session: requests.Session,
) -> dict[str, Any]:
    """
    TikWM supports GET and POST.
    POST is preferred because URLs with query strings are cleaner in form data.
    """
    response = session.post(
        API_URL,
        data={
            "url": input_url,
            "hd": "1" if hd else "0",
        },
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/140.0.0.0 Safari/537.36"
            ),
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://www.tikwm.com/",
        },
        timeout=timeout,
    )

    if response.status_code == 429:
        raise TikWMError("TikWM rate limit: HTTP 429")

    if response.status_code >= 500:
        raise TikWMError(
            f"TikWM temporary server error: HTTP {response.status_code}"
        )

    if response.status_code != 200:
        raise TikWMError(
            f"TikWM HTTP {response.status_code}: {response.text[:500]}"
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise TikWMError(
            f"TikWM вернул не JSON: {response.text[:500]}"
        ) from exc

    if not isinstance(payload, dict):
        raise TikWMError(
            f"Неожиданный формат TikWM: {type(payload).__name__}"
        )

    code = payload.get("code")

    if code != 0:
        raise TikWMError(
            f"TikWM error code={code}: {payload.get('msg')}"
        )

    data = payload.get("data")
    if not isinstance(data, dict):
        raise TikWMError(
            f"TikWM response не содержит data: {payload}"
        )

    return payload


def fetch_tiktok(
    input_url: str,
    *,
    hd: bool = False,
    timeout: float = 30.0,
    retries: int = 2,
    retry_delay: float = 1.2,
    session: requests.Session | None = None,
) -> tuple[TikTokMetrics, dict[str, Any]]:
    """
    Fetch one public TikTok post.

    No token/key/login is needed.

    retry_delay defaults above 1 second because TikWM's public API
    historically rate-limits frequent free requests.
    """
    if not input_url or not input_url.strip():
        raise ValueError("TikTok URL/ID пустой")

    input_url = input_url.strip()

    own_session = session is None
    s = session or requests.Session()

    last_error: Exception | None = None

    try:
        for attempt in range(retries + 1):
            try:
                raw = _request_once(
                    input_url,
                    hd=hd,
                    timeout=timeout,
                    session=s,
                )

                result = normalize(raw["data"], input_url)

                # We require at least an ID or one engagement metric.
                if (
                    result.video_id is None
                    and all(
                        x is None
                        for x in (
                            result.views,
                            result.likes,
                            result.comments,
                            result.shares,
                            result.saves,
                        )
                    )
                ):
                    raise TikWMError(
                        "TikWM вернул data, но видео/метрики не распознаны"
                    )

                return result, raw

            except (
                requests.Timeout,
                requests.ConnectionError,
                TikWMError,
            ) as exc:
                last_error = exc

                if attempt >= retries:
                    break

                # Public endpoint: don't hammer it.
                time.sleep(retry_delay * (attempt + 1))

        raise TikWMError(
            f"Не удалось получить TikTok после {retries + 1} попыток: "
            f"{last_error}"
        )

    finally:
        if own_session:
            s.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="TikTok stats via free TikWM API"
    )

    parser.add_argument(
        "url",
        help="TikTok video/photo URL, short URL or video ID",
    )

    parser.add_argument(
        "--hd",
        action="store_true",
        help="Попросить TikWM также получить HD video URL",
    )

    parser.add_argument(
        "--raw",
        action="store_true",
        help="Вывести также полный ответ TikWM",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout, default=30",
    )

    parser.add_argument(
        "--retries",
        type=int,
        default=2,
        help="Количество повторных попыток, default=2",
    )

    args = parser.parse_args()

    try:
        result, raw = fetch_tiktok(
            args.url,
            hd=args.hd,
            timeout=args.timeout,
            retries=max(0, args.retries),
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output: dict[str, Any]

    if args.raw:
        output = {
            "normalized": result.to_dict(),
            "raw": raw,
        }
    else:
        output = result.to_dict()

    print(
        json.dumps(
            output,
            ensure_ascii=False,
            indent=2,
        )
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
