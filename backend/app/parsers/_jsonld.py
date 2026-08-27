import json

from bs4 import BeautifulSoup

_INTERACTION_MAP = {
    "WatchAction": "views",
    "ViewAction": "views",
    "LikeAction": "likes",
    "CommentAction": "comments",
    "ShareAction": "reposts",
}


def extract_interaction_counts(html: str) -> dict[str, int]:
    """Best-effort extraction of schema.org InteractionCounter blocks
    commonly embedded as JSON-LD on content pages (VideoObject/Article)."""
    soup = BeautifulSoup(html, "html.parser")
    counts: dict[str, int] = {}

    def add_count(metric: str, value: object) -> None:
        try:
            count = int(value)
        except (TypeError, ValueError):
            return
        counts[metric] = counts.get(metric, 0) + count

    def visit(item: object) -> None:
        if isinstance(item, list):
            for child in item:
                visit(child)
            return
        if not isinstance(item, dict):
            return

        if "commentCount" in item:
            add_count("comments", item.get("commentCount"))

        for stat in item.get("interactionStatistic", []) or []:
            if not isinstance(stat, dict):
                continue
            interaction_type = (stat.get("interactionType") or "").rsplit("/", 1)[-1]
            metric = _INTERACTION_MAP.get(interaction_type)
            if metric and "userInteractionCount" in stat:
                add_count(metric, stat.get("userInteractionCount"))

        graph = item.get("@graph")
        if graph:
            visit(graph)

    for script in soup.find_all("script", type="application/ld+json"):
        try:
            payload = json.loads(script.string or "{}")
        except (json.JSONDecodeError, TypeError):
            continue
        visit(payload)

    return counts
