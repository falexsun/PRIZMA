import re
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app.models.enums import Platform

_TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "ysclid", "yclid", "from", "z",
}

_HOST_RULES: list[tuple[re.Pattern, str, Platform]] = [
    (re.compile(r"^(www\.)?vk\.(com|ru)$"), "vk.ru", Platform.vk),
    (re.compile(r"^(www\.)?vkvideo\.ru$"), "vkvideo.ru", Platform.vk),
    (re.compile(r"^(www\.)?t\.me$"), "t.me", Platform.telegram),
    (re.compile(r"^(www\.)?telegram\.me$"), "t.me", Platform.telegram),
    (re.compile(r"^(www\.)?(youtube\.com|youtu\.be)$"), "youtube.com", Platform.youtube),
    # vm./vt. are TikTok's own short-link redirect domains - collapsing them into
    # "tiktok.com" produces a path that doesn't exist on the main domain (404).
    # Keep each host distinct; only strip the cosmetic "www." prefix.
    (re.compile(r"^(www\.)?tiktok\.com$"), "tiktok.com", Platform.tiktok),
    (re.compile(r"^vm\.tiktok\.com$"), "vm.tiktok.com", Platform.tiktok),
    (re.compile(r"^vt\.tiktok\.com$"), "vt.tiktok.com", Platform.tiktok),
    (re.compile(r"^m\.tiktok\.com$"), "m.tiktok.com", Platform.tiktok),
    (re.compile(r"^(www\.)?instagram\.com$"), "instagram.com", Platform.instagram),
    (re.compile(r"^(www\.)?dzen\.ru$"), "dzen.ru", Platform.dzen),
    (re.compile(r"^(www\.)?max\.ru$"), "max.ru", Platform.max_ru),
    (re.compile(r"^(www\.|m\.|web\.)?ok\.ru$"), "ok.ru", Platform.ok),
]


class UnsupportedUrlError(ValueError):
    pass


def detect_platform(host: str) -> tuple[str, Platform] | None:
    for pattern, canonical_host, platform in _HOST_RULES:
        if pattern.match(host):
            return canonical_host, platform
    return None


def normalize_url(raw_url: str) -> tuple[str, Platform]:
    raw_url = raw_url.strip()
    parsed = urlparse(raw_url if "://" in raw_url else f"https://{raw_url}")

    match = detect_platform(parsed.netloc.lower())
    if match is None:
        raise UnsupportedUrlError(f"Unsupported platform for URL: {raw_url}")

    canonical_host, platform = match

    query = [(k, v) for k, v in parse_qsl(parsed.query) if k.lower() not in _TRACKING_PARAMS]
    path = parsed.path.rstrip("/") or ""

    # VK: ?w=wall-XXX_YYY or ?z=video-XXX_YYY → /wall-XXX_YYY or /video-XXX_YYY
    if platform == Platform.vk:
        qs_dict = dict(parse_qsl(parsed.query))
        for param in ("w", "z"):
            val = qs_dict.get(param, "")
            if val and re.match(r"(wall|video|clip)-?\d+_\d+", val):
                path = "/" + val
                query = [(k, v) for k, v in query if k != param]
                break
        # vkvideo.ru/@username/video-XXX_YYY → /video-XXX_YYY
        vkvideo_match = re.search(r"(/(?:wall|video|clip)-?\d+_\d+)", path)
        if vkvideo_match and canonical_host == "vkvideo.ru":
            path = vkvideo_match.group(1)

    normalized = urlunparse(("https", canonical_host, path, "", urlencode(query), ""))
    return normalized, platform


def extract_post_external_id(normalized_url: str, platform: Platform) -> str | None:
    parsed = urlparse(normalized_url)
    path = parsed.path.strip("/")
    if not path:
        return None

    if platform == Platform.vk:
        # Wall posts use "wall-1_2"; clips and videos use "clip-1_2" / "video-1_2".
        # All three share the same "<owner>_<item>" id shape once the prefix is stripped.
        match = re.search(r"(?:wall|video|clip)(-?\d+_\d+)", path)
        if match:
            return match.group(1)
        # Fallback: check ?w= or ?z= parameter for VK links like /name?w=wall-XXX_YYY
        qs_dict = dict(parse_qsl(parsed.query))
        for param in ("w", "z"):
            val = qs_dict.get(param, "")
            if val:
                w_match = re.search(r"(?:wall|video|clip)(-?\d+_\d+)", val)
                if w_match:
                    return w_match.group(1)
        return path
    if platform == Platform.youtube:
        if "watch" in path:
            qs = dict(parse_qsl(parsed.query))
            return qs.get("v")
        return path.split("/")[-1]
    return path.split("/")[-1]
