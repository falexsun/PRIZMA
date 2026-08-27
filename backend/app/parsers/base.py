from dataclasses import dataclass, field


@dataclass
class Metrics:
    likes: int = 0
    reposts: int = 0
    comments: int = 0
    saves: int = 0
    views: int = 0
    hashtags: list[str] = field(default_factory=list)


class ParserUnavailableError(Exception):
    """Raised when a platform cannot be fetched right now (rate limit, blocked, not implemented)."""


class ParserNotFoundError(Exception):
    """Raised when the referenced post no longer exists."""
