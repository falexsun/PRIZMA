import asyncio
import time
from datetime import datetime, timedelta, timezone

import httpx
import redis
from celery.exceptions import SoftTimeLimitExceeded
from sqlalchemy import select

from app.core.config import settings
from app.db.sync_session import SyncSessionLocal
from app.models import FetchJob, Link, LinkMetrics, Message, Subscription, SubscriptionPost, VKGroup, VKGroupPost
from app.models.enums import FetchStatus
from app.parsers.source_discovery import discover_posts
from app.parsers.base import ParserNotFoundError, ParserUnavailableError
from app.parsers.registry import get_parser
from app.services import config_service
from app.services.scheduling import UNAVAILABLE_RETRY_MINUTES, next_interval_minutes
from app.services.si import calc_si
from app.services.snapshot import recompute_message_snapshot
from app.services.url_normalize import normalize_url
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

        # Check if this link is from a VK group and still needs tracking (< 24h old)
        vk_group_post = session.execute(
            select(VKGroupPost).where(VKGroupPost.link_id == link.id)
        ).scalar_one_or_none()

        if vk_group_post is not None:
            post_age = now - vk_group_post.post_created_at.replace(tzinfo=timezone.utc)
            if post_age < timedelta(hours=POST_MAX_AGE_HOURS):
                # Reschedule: calculate next interval based on platform and post age
                interval = next_interval_minutes(link.platform, vk_group_post.post_created_at, now)
                job.status = FetchStatus.pending
                job.next_run_at = now + timedelta(minutes=interval)
                job.last_error = None
                session.commit()
            else:
                # Post is older than 24h, stop tracking
                job.status = FetchStatus.success
                job.last_error = None
                session.commit()
        else:
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


# --- VK Group auto-tracking ---

VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.199"
POST_MAX_AGE_HOURS = 24


def _vk_rate_limit_sync() -> None:
    """Wait until a rate-limit slot is available (shared across all workers via Redis)."""
    r = redis.from_url(settings.redis_url, decode_responses=True)
    for _ in range(40):
        now = time.time()
        last = float(r.get("vk:rate_limit:last_ts") or 0)
        if now - last >= 0.5:
            r.set("vk:rate_limit:last_ts", now, ex=60)
            return
        time.sleep(0.05)


def _fetch_vk_wall_page_sync(group_id: int, count: int = 20, offset: int = 0) -> tuple[list[dict], int]:
    """Fetch one page of wall posts from a VK group. Returns (items, total_count)."""
    vk_token = settings.vk_user_token or settings.vk_service_token
    if not vk_token:
        raise RuntimeError("VK token is not configured")

    _vk_rate_limit_sync()

    params = {
        "owner_id": -group_id,  # negative for groups
        "count": count,
        "offset": offset,
        "access_token": vk_token,
        "v": VK_API_VERSION,
    }

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    response = httpx.get(f"{VK_API_BASE}/wall.get", params=params, timeout=timeout)
    response.raise_for_status()
    data = response.json()

    if "error" in data:
        error_msg = data["error"].get("error_msg", "Unknown VK API error")
        raise RuntimeError(f"VK API error: {error_msg}")

    response_data = data.get("response", {})
    if isinstance(response_data, dict):
        items = response_data.get("items", [])
        total = response_data.get("count", len(items))
    else:
        items = response_data if isinstance(response_data, list) else []
        total = len(items)
    return items, total


def _fetch_all_wall_posts_sync(group_id: int) -> list[dict]:
    """Fetch ALL wall posts from a VK group with pagination."""
    all_items: list[dict] = []
    offset = 0
    page_size = 100
    max_pages = 100  # safety limit: 100 * 100 = 10000 posts max

    for _ in range(max_pages):
        items, _ = _fetch_vk_wall_page_sync(group_id, count=page_size, offset=offset)
        if not items:
            break
        all_items.extend(items)
        if len(items) < page_size:
            break
        offset += page_size

    return all_items


@celery_app.task(name="app.workers.tasks.check_all_vk_groups")
def check_all_vk_groups() -> int:
    """Periodic task: enqueue checks for all due VK groups."""
    now = datetime.now(timezone.utc)
    with SyncSessionLocal() as session:
        config_service.refresh_settings_sync(session)

        groups = session.execute(
            select(VKGroup).where(VKGroup.is_active == True)
        ).scalars().all()

        enqueued = 0
        for group in groups:
            if group.last_checked_at is not None:
                last = group.last_checked_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                elapsed = (now - last).total_seconds() / 60
                if elapsed < group.check_interval_minutes:
                    continue

            check_vk_group_posts.delay(group.id)
            enqueued += 1

    return enqueued


def _add_new_posts(session, group, message, posts, existing_ids, existing_link_urls, now, apply_age_limit=True, cutoff=None):
    """Process a list of wall posts, creating links and fetch jobs for new ones."""
    new_posts_count = 0
    for post in posts:
        post_id_str = str(post.get("id", ""))
        owner_id = post.get("owner_id", -group.vk_group_id)
        external_id = f"{owner_id}_{post_id_str}"

        if external_id in existing_ids:
            continue

        post_date = datetime.fromtimestamp(post.get("date", 0), tz=timezone.utc)

        # In normal mode: skip posts older than 24 hours
        if apply_age_limit:
            age_hours = (now - post_date).total_seconds() / 3600
            if age_hours > POST_MAX_AGE_HOURS:
                continue

        # Skip posts that existed before the group was last checked
        if cutoff is not None and post_date < cutoff:
            continue

        post_url = f"https://vk.com/wall{external_id}"
        try:
            normalized_url, platform = normalize_url(post_url)
        except Exception:
            continue

        if normalized_url in existing_link_urls:
            existing_link = session.execute(
                select(Link).where(
                    Link.message_id == message.id,
                    Link.url_normalized == normalized_url,
                )
            ).scalar_one_or_none()
            if existing_link:
                group_post = VKGroupPost(
                    vk_group_id=group.id,
                    post_external_id=external_id,
                    link_id=existing_link.id,
                    post_created_at=post_date,
                )
                session.add(group_post)
            continue

        link = Link(
            message_id=message.id,
            url_raw=post_url,
            url_normalized=normalized_url,
            platform=platform,
        )
        session.add(link)
        session.flush()

        group_post = VKGroupPost(
            vk_group_id=group.id,
            post_external_id=external_id,
            link_id=link.id,
            post_created_at=post_date,
        )
        session.add(group_post)

        fetch_job = FetchJob(link_id=link.id, next_run_at=now)
        session.add(fetch_job)

        existing_ids.add(external_id)
        existing_link_urls.add(normalized_url)
        new_posts_count += 1

    return new_posts_count


@celery_app.task(name="app.workers.tasks.check_vk_group_posts", bind=True, max_retries=2)
def check_vk_group_posts(self, vk_group_id: int) -> dict:
    """Check a single VK group for new posts and create links + fetch jobs."""
    now = datetime.now(timezone.utc)

    with SyncSessionLocal() as session:
        config_service.refresh_settings_sync(session)

        group = session.get(VKGroup, vk_group_id)
        if group is None:
            return {"status": "group_not_found"}

        if not group.is_active:
            return {"status": "group_inactive"}

        if group.message_id is None:
            return {"status": "no_message"}

        message = session.get(Message, group.message_id)
        if message is None:
            return {"status": "message_not_found"}

        is_backfill = group.backfill and not group.backfill_completed

        # Fetch wall posts from VK
        try:
            if is_backfill:
                posts = _fetch_all_wall_posts_sync(group.vk_group_id)
            else:
                posts, _ = _fetch_vk_wall_page_sync(group.vk_group_id, count=20)
        except Exception as exc:
            group.last_checked_at = now
            session.commit()
            raise self.retry(exc=exc, countdown=120)

        existing_posts = session.execute(
            select(VKGroupPost.post_external_id).where(VKGroupPost.vk_group_id == group.id)
        ).scalars().all()
        existing_ids = set(existing_posts)

        existing_links = session.execute(
            select(Link.url_normalized).where(Link.message_id == message.id)
        ).scalars().all()
        existing_link_urls = set(existing_links)

        if is_backfill:
            # Backfill mode: fetch ALL posts, no age limit, no date cutoff
            new_posts_count = _add_new_posts(
                session, group, message, posts,
                existing_ids, existing_link_urls, now,
                apply_age_limit=False, cutoff=None,
            )
            group.backfill_completed = True
        else:
            # Normal mode: only posts newer than last check, with 24h limit
            cutoff = group.last_checked_at or now
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            new_posts_count = _add_new_posts(
                session, group, message, posts,
                existing_ids, existing_link_urls, now,
                apply_age_limit=True, cutoff=cutoff,
            )

        all_links = session.execute(
            select(Link).where(Link.message_id == message.id)
        ).scalars().all()
        if message.snapshot:
            message.snapshot.links_count = len(all_links)

        group.last_checked_at = now
        session.commit()

        return {
            "status": "ok",
            "vk_group_id": group.id,
            "new_posts": new_posts_count,
            "total_wall_posts": len(posts),
            "backfill": is_backfill,
        }


# --- Generic subscription auto-tracking (all platforms) ---

SUB_POST_MAX_AGE_HOURS = 24


def _add_subscription_posts(session, sub, message, discovered, existing_ids, existing_link_urls, now, apply_age_limit=True, cutoff=None):
    """Process discovered posts, creating links and fetch jobs for new ones."""
    new_count = 0
    for dp in discovered:
        if dp.external_id in existing_ids:
            continue

        post_date = datetime.fromtimestamp(dp.timestamp, tz=timezone.utc) if dp.timestamp > 0 else now

        if apply_age_limit and dp.timestamp > 0:
            age_hours = (now - post_date).total_seconds() / 3600
            if age_hours > SUB_POST_MAX_AGE_HOURS:
                continue

        if cutoff is not None and dp.timestamp > 0 and post_date < cutoff:
            continue

        try:
            normalized_url, platform = normalize_url(dp.url)
        except Exception:
            continue

        if normalized_url in existing_link_urls:
            existing_link = session.execute(
                select(Link).where(Link.message_id == message.id, Link.url_normalized == normalized_url)
            ).scalar_one_or_none()
            if existing_link:
                session.add(SubscriptionPost(
                    subscription_id=sub.id, post_external_id=dp.external_id,
                    link_id=existing_link.id, post_created_at=post_date,
                ))
            continue

        link = Link(message_id=message.id, url_raw=dp.url, url_normalized=normalized_url, platform=platform)
        session.add(link)
        session.flush()

        session.add(SubscriptionPost(
            subscription_id=sub.id, post_external_id=dp.external_id,
            link_id=link.id, post_created_at=post_date,
        ))
        session.add(FetchJob(link_id=link.id, next_run_at=now))

        existing_ids.add(dp.external_id)
        existing_link_urls.add(normalized_url)
        new_count += 1

    return new_count


@celery_app.task(name="app.workers.tasks.check_all_subscriptions")
def check_all_subscriptions() -> int:
    """Periodic task: enqueue checks for all due subscriptions."""
    now = datetime.now(timezone.utc)
    with SyncSessionLocal() as session:
        config_service.refresh_settings_sync(session)
        subs = session.execute(select(Subscription).where(Subscription.is_active == True)).scalars().all()
        enqueued = 0
        for sub in subs:
            if sub.last_checked_at is not None:
                last = sub.last_checked_at
                if last.tzinfo is None:
                    last = last.replace(tzinfo=timezone.utc)
                if (now - last).total_seconds() / 60 < sub.check_interval_minutes:
                    continue
            check_subscription_posts.delay(sub.id)
            enqueued += 1
    return enqueued


@celery_app.task(name="app.workers.tasks.check_subscription_posts", bind=True, max_retries=2)
def check_subscription_posts(self, subscription_id: int) -> dict:
    """Check a single subscription for new posts and create links + fetch jobs."""
    now = datetime.now(timezone.utc)

    with SyncSessionLocal() as session:
        config_service.refresh_settings_sync(session)

        sub = session.get(Subscription, subscription_id)
        if sub is None:
            return {"status": "not_found"}
        if not sub.is_active:
            return {"status": "inactive"}
        if sub.message_id is None:
            return {"status": "no_message"}

        message = session.get(Message, sub.message_id)
        if message is None:
            return {"status": "message_not_found"}

        is_backfill = sub.backfill and not sub.backfill_completed

        try:
            discovered = discover_posts(sub.platform, sub.source_id, backfill=is_backfill)
        except Exception as exc:
            sub.last_checked_at = now
            session.commit()
            raise self.retry(exc=exc, countdown=120)

        existing_posts = session.execute(
            select(SubscriptionPost.post_external_id).where(SubscriptionPost.subscription_id == sub.id)
        ).scalars().all()
        existing_ids = set(existing_posts)

        existing_links = session.execute(
            select(Link.url_normalized).where(Link.message_id == message.id)
        ).scalars().all()
        existing_link_urls = set(existing_links)

        if is_backfill:
            new_count = _add_subscription_posts(
                session, sub, message, discovered, existing_ids, existing_link_urls, now,
                apply_age_limit=False, cutoff=None,
            )
            sub.backfill_completed = True
        else:
            cutoff = sub.last_checked_at or now
            if cutoff.tzinfo is None:
                cutoff = cutoff.replace(tzinfo=timezone.utc)
            new_count = _add_subscription_posts(
                session, sub, message, discovered, existing_ids, existing_link_urls, now,
                apply_age_limit=True, cutoff=cutoff,
            )

        all_links = session.execute(
            select(Link).where(Link.message_id == message.id)
        ).scalars().all()
        if message.snapshot:
            message.snapshot.links_count = len(all_links)

        sub.last_checked_at = now
        session.commit()

        return {
            "status": "ok",
            "subscription_id": sub.id,
            "platform": sub.platform.value,
            "new_posts": new_count,
            "total_discovered": len(discovered),
            "backfill": is_backfill,
        }
