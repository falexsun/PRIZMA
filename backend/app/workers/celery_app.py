from celery import Celery

from app.core.config import settings

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
    # Hard timeout: kill the task if it exceeds 90 seconds.
    # Prevents a hung parser (Playwright, yt-dlp, browser scraping) from
    # blocking the worker indefinitely.
    task_time_limit=90,
    # Soft timeout: raises SoftTimeLimitExceeded at 75 seconds so the
    # task can clean up (close browser, release resources) before the
    # hard kill at 90s.
    task_soft_time_limit=75,
    # Run up to 4 fetch tasks in parallel per worker process.
    # Without this the default is 1, so a single slow MAX/Dzen Playwright
    # fetch blocks every other platform behind it.
    worker_concurrency=4,
)

celery_app.conf.beat_schedule = {
    "enqueue-due-fetch-jobs": {
        "task": "app.workers.tasks.enqueue_due_fetch_jobs",
        "schedule": 60.0,
    },
}
