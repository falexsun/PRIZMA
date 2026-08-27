import re
import base64
from pathlib import Path
from urllib.parse import urlparse

from app.core.config import settings
from app.parsers.base import Metrics, ParserNotFoundError, ParserUnavailableError

# Regex for extracting counters from the rendered MAX page text. The MAX web
# client is a SvelteKit SPA; public preview pages show the post content but
# hide engagement counters. With a valid session (created by max_login.py) the
# full post is rendered and counters become visible in the DOM text.
_COUNTER_PATTERNS = {
    "views": [
        re.compile(r"([\d\s\xa0]+)\s*просмотр", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*views?", re.IGNORECASE),
    ],
    "likes": [
        re.compile(r"([\d\s\xa0]+)\s*лайк", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*реакц", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*likes?", re.IGNORECASE),
    ],
    "comments": [
        re.compile(r"([\d\s\xa0]+)\s*комментари", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*ответ", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*comments?", re.IGNORECASE),
    ],
    "reposts": [
        re.compile(r"([\d\s\xa0]+)\s*подел", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*пересл", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*shares?", re.IGNORECASE),
    ],
    "saves": [
        re.compile(r"([\d\s\xa0]+)\s*сохран", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*избран", re.IGNORECASE),
        re.compile(r"([\d\s\xa0]+)\s*saves?", re.IGNORECASE),
    ],
}

_PREVIEW_MARKERS = [
    "скачать приложение",
    "открыть в браузере",
    "перейти к посту",
    "войдите в max",
    "войти по номеру телефона",
]


def _parse_counter(text: str, patterns: list[re.Pattern]) -> int:
    for pattern in patterns:
        match = pattern.search(text)
        if match:
            raw = match.group(1).replace(" ", "").replace("\xa0", "").replace("\u202f", "")
            try:
                return int(raw)
            except ValueError:
                return 0
    return 0


def _pymax_work_dir() -> Path:
    path = Path(settings.max_session_path)
    return path if not path.suffix else path.with_suffix("")


def _native_session_available() -> bool:
    work_dir = _pymax_work_dir()
    return (work_dir / "session.db").exists() and (work_dir / "phone.txt").exists()


def _decode_message_id(encoded: str) -> int:
    padding = "=" * (-len(encoded) % 4)
    return int.from_bytes(base64.urlsafe_b64decode(encoded + padding), "big")


async def _fetch_via_pymax(url: str) -> Metrics:
    """Read public post statistics through the authenticated MAX socket API."""
    try:
        from pymax.payloads import UserAgentPayload
        from app.services.max_client import ContentTrackerMaxClient
    except ImportError as exc:
        raise ParserUnavailableError("maxapi-python is not installed") from exc

    work_dir = _pymax_work_dir()
    phone_path = work_dir / "phone.txt"
    session_db = work_dir / "session.db"
    if not phone_path.exists() or not session_db.exists():
        raise ParserUnavailableError("MAX native session is not configured")

    parts = urlparse(url).path.strip("/").split("/")
    if len(parts) != 2:
        raise ParserNotFoundError(f"Unsupported MAX post URL: {url}")
    _, encoded_message_id = parts
    message_id = _decode_message_id(encoded_message_id)

    client = ContentTrackerMaxClient(
        phone=phone_path.read_text(encoding="utf-8").strip(),
        work_dir=str(work_dir),
        headers=UserAgentPayload(device_type="DESKTOP", app_version="25.12.13"),
        reconnect=False,
    )
    try:
        await client.connect()
        # A socket handshake alone leaves the session in AUTHENTICATED state.
        # Link and message methods require the post-login sync to reach ONLINE.
        await client._sync(client.user_agent)
        from pymax import Opcode

        # LINK_INFO validates both the channel and the encoded post id without
        # subscribing the account to the channel.
        link_response = await client._send_and_wait(
            opcode=Opcode.LINK_INFO,
            payload={"link": url},
        )
        link_payload = link_response.get("payload", {})
        channel = link_payload.get("chat") or {}
        linked_message = link_payload.get("message") or {}
        if link_payload.get("error") or not channel or not linked_message:
            raise ParserNotFoundError(f"MAX post not found: {url}")
        if int(linked_message.get("id", 0)) != message_id:
            raise ParserNotFoundError(f"MAX post id mismatch: {url}")

        # MAX's dedicated MSG_GET_STAT operation is not returned for public
        # channels. CHAT_HISTORY contains the same public data in
        # message.stats.views and also includes reactionInfo.
        history_response = await client._send_and_wait(
            opcode=Opcode.CHAT_HISTORY,
            payload={
                "chatId": int(channel["id"]),
                "from": int(linked_message["time"]) + 1,
                "forward": 0,
                "backward": 5,
            },
        )
        history_payload = history_response.get("payload", {})
        if history_payload.get("error"):
            raise ParserUnavailableError(f"MAX history error: {history_payload['error']}")
        message = next(
            (
                item
                for item in history_payload.get("messages", [])
                if int(item.get("id", 0)) == message_id
            ),
            None,
        )
        if message is None:
            raise ParserNotFoundError(f"MAX post not found in channel history: {url}")

        reaction_data = message.get("reactionInfo") or {}
        views = (message.get("stats") or {}).get("views", 0) or 0
        return Metrics(
            likes=reaction_data.get("totalCount", 0) or 0,
            reposts=0,
            comments=0,
            saves=0,
            views=views,
        )
    finally:
        try:
            await client.close()
        except Exception:
            pass


async def _render_and_extract(url: str) -> Metrics:
    try:
        from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeout
    except ImportError as exc:
        raise ParserUnavailableError("playwright is not installed") from exc

    session_path = Path(settings.max_session_path)
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context_kwargs = {
            "user_agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/135.0.0.0 Safari/537.36"
            ),
            "locale": "ru-RU",
        }
        if session_path.exists():
            context_kwargs["storage_state"] = str(session_path)

        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        try:
            response = await page.goto(url, wait_until="networkidle", timeout=30000)
        except PlaywrightTimeout:
            response = None

        if response is not None and response.status == 404:
            await browser.close()
            raise ParserNotFoundError(f"MAX post not found: {url}")

        # Give the SPA a moment to hydrate and render any lazy counters.
        await page.wait_for_timeout(2000)
        body_text = (await page.locator("body").inner_text()).lower()

        # Persist an updated session (refreshed cookies/localStorage) after each run.
        session_path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(session_path))
        await browser.close()

    if any(marker in body_text for marker in _PREVIEW_MARKERS):
        # Public preview pages do not expose engagement counters; a logged-in
        # session is required to see the full post with stats.
        raise ParserUnavailableError(
            "MAX public preview does not show engagement counters. "
            "Run `python -m app.parsers.max_login` once to create a session."
        )

    return Metrics(
        likes=_parse_counter(body_text, _COUNTER_PATTERNS["likes"]),
        reposts=_parse_counter(body_text, _COUNTER_PATTERNS["reposts"]),
        comments=_parse_counter(body_text, _COUNTER_PATTERNS["comments"]),
        saves=_parse_counter(body_text, _COUNTER_PATTERNS["saves"]),
        views=_parse_counter(body_text, _COUNTER_PATTERNS["views"]),
    )


async def fetch(url: str) -> Metrics:
    if not settings.max_headless_enabled:
        raise ParserUnavailableError(
            "MAX metrics collection is disabled (MAX_HEADLESS_ENABLED=false)"
        )

    try:
        if _native_session_available():
            return await _fetch_via_pymax(url)
        return await _render_and_extract(url)
    except ParserNotFoundError:
        raise
    except ParserUnavailableError:
        raise
    except Exception as exc:
        raise ParserUnavailableError(f"MAX headless fetch failed: {exc}") from exc
