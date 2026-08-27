import asyncio
from datetime import datetime, timedelta, timezone

from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from app.db.sync_session import SyncSessionLocal
from app.models import FetchJob, Link, LinkMetrics, Message
from app.models.enums import FetchStatus
from app.parsers.base import ParserNotFoundError, ParserUnavailableError
from app.parsers.registry import get_parser
from app.services import config_service
from app.services.scheduling import UNAVAILABLE_RETRY_MINUTES
from app.services.si import calc_si
from app.services.snapshot import recompute_message_snapshot
from app.services.ws_publish import publish_message_update
from app.workers.celery_app import celery_app


@celery_app.task(name="app.workers.tasks.enqueue_due_fetch_jobs")
def enqueue_due_fetch_jobs() -> int:
    now = datetime.now(timezone.utc)
    with SyncSessionLocal() as session:
        due_jobs = session.execute(
            select(FetchJob).where(FetchJob.status == FetchStatus.pending, FetchJob.next_run_at <= now)
        ).scalars().all()

        job_ids = [job.id for job in due_jobs]
        for job in due_jobs:
            job.status = FetchStatus.in_progress
        session.commit()

    for job_id in job_ids:
        fetch_link_metrics.delay(job_id)

    return len(job_ids)


@celery_app.task(name="app.workers.tasks.fetch_link_metrics", bind=True, max_retries=3)
def fetch_link_metrics(self, fetch_job_id: int) -> None:
    now = datetime.now(timezone.utc)

    with SyncSessionLocal() as session:
        config_service.refresh_settings_sync(session)

        job = session.get(FetchJob, fetch_job_id)
        if job is None:
            return

        link = session.get(Link, job.link_id)
        if link is None:
            job.status = FetchStatus.failed
            job.last_error = f"Link {job.link_id} not found (deleted)"
            session.commit()
            return

        message = session.get(Message, link.message_id)
        if message is None:
            job.status = FetchStatus.failed
            job.last_error = f"Message {link.message_id} not found (deleted)"
            session.commit()
            return

        job.attempts += 1
        parser = get_parser(link.platform)

        try:
            metrics = asyncio.run(parser(link.url_normalized))
        except ParserNotFoundError as exc:
            job.status = FetchStatus.failed
            job.last_error = str(exc)
            session.commit()
            return
        except ParserUnavailableError as exc:
            job.status = FetchStatus.unavailable
            job.last_error = str(exc)
            job.next_run_at = now + timedelta(minutes=UNAVAILABLE_RETRY_MINUTES)
            session.commit()
            return
        except SoftTimeLimitExceeded:
            job.status = FetchStatus.unavailable
            job.last_error = "Task timed out (soft limit exceeded)"
            job.next_run_at = now + timedelta(minutes=UNAVAILABLE_RETRY_MINUTES)
            session.commit()
            return
        except Exception as exc:  # network errors, timeouts, etc.
            job.last_error = str(exc)
            if job.attempts >= self.max_retries:
                job.status = FetchStatus.failed
                session.commit()
                return
            session.commit()
            raise self.retry(exc=exc, countdown=60)

        si = calc_si(metrics.likes, metrics.reposts, metrics.comments, metrics.saves)
        session.add(
            LinkMetrics(
                link_id=link.id,
                likes=metrics.likes,
                reposts=metrics.reposts,
                comments=metrics.comments,
                saves=metrics.saves,
                views=metrics.views,
                si=si,
            )
        )

        # Update hashtags if extracted
        if metrics.hashtags:
            link.hashtags = ",".join(metrics.hashtags)

        snapshot = recompute_message_snapshot(session, message.id)

        job.status = FetchStatus.success
        job.last_error = None

        session.commit()

        publish_message_update(
            message.id,
            message.user_id,
            {
                "message_id": message.id,
                "si_total": snapshot.si_total,
                "views_total": snapshot.views_total,
                "link_id": link.id,
                "link_si": si,
            },
        )
