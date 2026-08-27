import re

# Matches #hashtag with Cyrillic, Latin, digits, underscores
_HASHTAG_RE = re.compile(r"#([\w\u0400-\u04ff]+)", re.UNICODE)


def extract_hashtags(text: str) -> list[str]:
    """Extract unique hashtags from text, preserving order, lowercased."""
    if not text:
        return []
    seen: set[str] = set()
    result: list[str] = []
    for match in _HASHTAG_RE.finditer(text):
        tag = match.group(1).lower()
        if tag not in seen:
            seen.add(tag)
            result.append(tag)
    return result
