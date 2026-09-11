from celery import Celery

from app.core.config import settings

# ---------------------------------------------------------------------------
# Queue architecture:
#   "fast"  — HTTP-based parsers (VK, Telegram, YouTube) — lightweight, fast
#   "heavy" — Playwright-based parsers (OK, TikTok, Instagram, Dzen, MAX) — slow, memory-hungry
#
# Each queue is served by a separate worker container with its own concurrency.
# This prevents a 60s OK Playwright crawl from starving VK metric fetches.
# ---------------------------------------------------------------------------

QUEUE_FAST = "fast"
QUEUE_HEAVY = "heavy"

celery_app = Celery(
    "content_tracker",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_time_limit=90,
    task_soft_time_limit=75,
    worker_concurrency=4,
    task_routes={
        # Heavy (Playwright) parsers go to their own queue
        "app.workers.tasks.fetch_link_metrics_heavy": {"queue": QUEUE_HEAVY},
        "app.workers.tasks.check_subscription_posts": {"queue": QUEUE_HEAVY},
        # Everything else stays on fast
        "app.workers.tasks.fetch_link_metrics": {"queue": QUEUE_FAST},
        "app.workers.tasks.enqueue_due_fetch_jobs": {"queue": QUEUE_FAST},
        "app.workers.tasks.check_all_vk_groups": {"queue": QUEUE_FAST},
        "app.workers.tasks.check_all_subscriptions": {"queue": QUEUE_FAST},
        "app.workers.tasks.check_vk_group_posts": {"queue": QUEUE_FAST},
    },
)

celery_app.conf.beat_schedule = {
    "enqueue-due-fetch-jobs": {
        "task": "app.workers.tasks.enqueue_due_fetch_jobs",
        "schedule": 60.0,
    },
    "check-all-vk-groups": {
        "task": "app.workers.tasks.check_all_vk_groups",
        "schedule": 300.0,
    },
    "check-all-subscriptions": {
        "task": "app.workers.tasks.check_all_subscriptions",
        "schedule": 300.0,
    },
}
