import re
from datetime import datetime, timezone
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import Link, Message, User, Subscription, SubscriptionPost
from app.models.enums import Platform, Tone
from app.schemas.subscription import (
    SubscriptionCreate, SubscriptionOut, SubscriptionPostOut, SubscriptionUpdate,
)
from app.services import config_service
from app.services.url_normalize import detect_platform

router = APIRouter(prefix="/subscriptions", tags=["subscriptions"], dependencies=[Depends(get_current_user)])


def _parse_source_url(url: str) -> tuple[Platform, str, str]:
    """Parse a social media URL and return (platform, source_id, screen_name).

    source_id is a platform-specific identifier used for API calls.
    screen_name is a human-readable name for display.
    """
    url = url.strip()

    # Handle bare @username for Telegram (e.g. "@news_heels_74")
    if url.startswith("@") and "/" not in url and "." not in url:
        username = url.lstrip("@")
        return Platform.telegram, username, username

    if not url.startswith("http"):
        url = "https://" + url

    parsed = urlparse(url)
    host = parsed.netloc.lower().lstrip("www.")
    path = parsed.path.strip("/")

    # VK: groups and users
    if host in ("vk.com", "vk.ru", "m.vk.com"):
        # https://vk.com/public12345, /club12345, /screen_name
        m = re.match(r"(?:public|club)(\d+)", path)
        if m:
            return Platform.vk, m.group(1), path
        # User profile: /username
        return Platform.vk, path, path

    # VK Video
    if host == "vkvideo.ru":
        return Platform.vk, path, path

    # Telegram
    if host in ("t.me", "telegram.me"):
        # https://t.me/channel_name or t.me/s/channel_name
        channel = path.replace("s/", "").split("/")[0]
        return Platform.telegram, channel, channel

    # YouTube
    if host in ("youtube.com", "youtu.be"):
        if path.startswith("channel/"):
            ch_id = path.split("/")[1]
            return Platform.youtube, ch_id, ch_id
        if path.startswith("@"):
            return Platform.youtube, path, path
        if host == "youtu.be":
            return Platform.youtube, path, path
        return Platform.youtube, path, path

    # TikTok
    if host in ("tiktok.com", "vm.tiktok.com", "vt.tiktok.com", "m.tiktok.com"):
        m = re.match(r"@([\w.]+)", path)
        if m:
            return Platform.tiktok, m.group(1), m.group(1)
        return Platform.tiktok, path, path

    # Instagram
    if host == "instagram.com":
        username = path.split("/")[0]
        if username:
            return Platform.instagram, username, username

    # Dzen
    if host == "dzen.ru":
        return Platform.dzen, path, path

    # MAX
    if host == "max.ru":
        return Platform.max_ru, path, path

    # OK
    if host == "ok.ru":
        # https://ok.ru/group/123456 or /profile/123456
        m = re.match(r"(?:group|profile)/(\d+)", path)
        if m:
            return Platform.ok, m.group(1), path
        return Platform.ok, path, path

    raise ValueError(f"Unsupported platform URL: {url}")


async def _resolve_source_info(platform: Platform, source_id: str, source_url: str) -> dict:
    """Try to get source name and photo from the platform API or page."""
    name = source_id
    screen_name = source_id
    photo_url = ""

    try:
        if platform == Platform.vk:
            vk_token = settings.vk_user_token or settings.vk_service_token
            if vk_token:
                identifier = source_id if source_id.lstrip("-").isdigit() else source_id
                timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
                async with httpx.AsyncClient(timeout=timeout) as client:
                    resp = await client.get(
                        "https://api.vk.com/method/groups.getById",
                        params={"group_ids": identifier, "access_token": vk_token, "v": "5.199"},
                    )
                    data = resp.json()
                    if "response" in data:
                        groups = data["response"].get("groups", [])
                        if groups:
                            name = groups[0].get("name", source_id)
                            screen_name = groups[0].get("screen_name", source_id)
                            photo_url = groups[0].get("photo_200", "")
        elif platform == Platform.telegram:
            name = f"@{source_id}"
            screen_name = source_id
    except Exception:
        pass

    return {"name": name, "screen_name": screen_name, "photo_url": photo_url}


@router.post("", response_model=SubscriptionOut, status_code=status.HTTP_201_CREATED)
async def create_subscription(
    payload: SubscriptionCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    await config_service.refresh_settings(db)

    try:
        platform, source_id, screen_name = _parse_source_url(payload.source_url)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    if payload.platform is not None:
        platform = payload.platform

    # Check if already exists
    existing = (
        await db.execute(
            select(Subscription).where(
                Subscription.platform == platform,
                Subscription.source_id == source_id,
            )
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "Subscription already exists")

    info = await _resolve_source_info(platform, source_id, payload.source_url)

    # Create a message for this subscription
    message = Message(
        user_id=user.id,
        department=user.department,
        tone=Tone.neutral,
        title=f"{platform.value}: {info['name']}",
        content_format="social_post",
    )
    db.add(message)
    await db.flush()

    now = datetime.now(timezone.utc)
    sub = Subscription(
        user_id=user.id,
        message_id=message.id,
        platform=platform,
        source_url=payload.source_url,
        source_id=source_id,
        name=info["name"],
        screen_name=info["screen_name"] or screen_name,
        photo_url=info["photo_url"],
        backfill=payload.backfill,
        check_interval_minutes=payload.check_interval_minutes,
        last_checked_at=None if payload.backfill else now,
    )
    db.add(sub)
    await db.commit()
    await db.refresh(sub)

    return SubscriptionOut(
        id=sub.id, platform=sub.platform, source_url=sub.source_url,
        source_id=sub.source_id, name=sub.name, screen_name=sub.screen_name,
        photo_url=sub.photo_url, is_active=sub.is_active,
        backfill=sub.backfill, backfill_completed=sub.backfill_completed,
        check_interval_minutes=sub.check_interval_minutes,
        last_checked_at=sub.last_checked_at, message_id=sub.message_id,
        posts_count=0, active_posts_count=0, created_at=sub.created_at,
    )


@router.get("", response_model=list[SubscriptionOut])
async def list_subscriptions(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SubscriptionOut]:
    query = select(Subscription).options(selectinload(Subscription.posts))
    if user.role.value != "admin":
        query = query.where(Subscription.user_id == user.id)
    query = query.order_by(Subscription.created_at.desc())

    subs = (await db.execute(query)).scalars().unique().all()
    now = datetime.now(timezone.utc)

    result = []
    for s in subs:
        posts_count = len(s.posts)
        active_count = sum(
            1 for p in s.posts
            if (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() < 86400
        )
        result.append(SubscriptionOut(
            id=s.id, platform=s.platform, source_url=s.source_url,
            source_id=s.source_id, name=s.name, screen_name=s.screen_name,
            photo_url=s.photo_url, is_active=s.is_active,
            backfill=s.backfill, backfill_completed=s.backfill_completed,
            check_interval_minutes=s.check_interval_minutes,
            last_checked_at=s.last_checked_at, message_id=s.message_id,
            posts_count=posts_count, active_posts_count=active_count,
            created_at=s.created_at,
        ))
    return result


@router.get("/{sub_id}", response_model=SubscriptionOut)
async def get_subscription(
    sub_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    s = (
        await db.execute(
            select(Subscription).options(selectinload(Subscription.posts)).where(Subscription.id == sub_id)
        )
    ).scalar_one_or_none()
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    if user.role.value != "admin" and s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")

    now = datetime.now(timezone.utc)
    posts_count = len(s.posts)
    active_count = sum(
        1 for p in s.posts
        if (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() < 86400
    )
    return SubscriptionOut(
        id=s.id, platform=s.platform, source_url=s.source_url,
        source_id=s.source_id, name=s.name, screen_name=s.screen_name,
        photo_url=s.photo_url, is_active=s.is_active,
        backfill=s.backfill, backfill_completed=s.backfill_completed,
        check_interval_minutes=s.check_interval_minutes,
        last_checked_at=s.last_checked_at, message_id=s.message_id,
        posts_count=posts_count, active_posts_count=active_count,
        created_at=s.created_at,
    )


@router.patch("/{sub_id}", response_model=SubscriptionOut)
async def update_subscription(
    sub_id: int,
    payload: SubscriptionUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> SubscriptionOut:
    s = (
        await db.execute(
            select(Subscription).options(selectinload(Subscription.posts)).where(Subscription.id == sub_id)
        )
    ).scalar_one_or_none()
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    if user.role.value != "admin" and s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")

    if payload.is_active is not None:
        s.is_active = payload.is_active
    if payload.check_interval_minutes is not None:
        s.check_interval_minutes = payload.check_interval_minutes
    await db.commit()
    await db.refresh(s)

    now = datetime.now(timezone.utc)
    posts_count = len(s.posts)
    active_count = sum(
        1 for p in s.posts
        if (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() < 86400
    )
    return SubscriptionOut(
        id=s.id, platform=s.platform, source_url=s.source_url,
        source_id=s.source_id, name=s.name, screen_name=s.screen_name,
        photo_url=s.photo_url, is_active=s.is_active,
        backfill=s.backfill, backfill_completed=s.backfill_completed,
        check_interval_minutes=s.check_interval_minutes,
        last_checked_at=s.last_checked_at, message_id=s.message_id,
        posts_count=posts_count, active_posts_count=active_count,
        created_at=s.created_at,
    )


@router.delete("/{sub_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_subscription(
    sub_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    s = (await db.execute(select(Subscription).where(Subscription.id == sub_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    if user.role.value != "admin" and s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    await db.delete(s)
    await db.commit()


@router.get("/{sub_id}/posts", response_model=list[SubscriptionPostOut])
async def list_subscription_posts(
    sub_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[SubscriptionPostOut]:
    s = (await db.execute(select(Subscription).where(Subscription.id == sub_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    if user.role.value != "admin" and s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")

    posts = (
        await db.execute(
            select(SubscriptionPost)
            .where(SubscriptionPost.subscription_id == sub_id)
            .order_by(SubscriptionPost.post_created_at.desc())
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    result = []
    for p in posts:
        age_hours = (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        is_tracking = age_hours < 24 and p.link_id is not None
        result.append(SubscriptionPostOut(
            id=p.id, post_external_id=p.post_external_id,
            link_id=p.link_id, post_created_at=p.post_created_at,
            first_seen_at=p.first_seen_at, is_tracking=is_tracking,
        ))
    return result


@router.post("/{sub_id}/check-now", status_code=status.HTTP_202_ACCEPTED)
async def check_subscription_now(
    sub_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    s = (await db.execute(select(Subscription).where(Subscription.id == sub_id))).scalar_one_or_none()
    if not s:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")
    if user.role.value != "admin" and s.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Subscription not found")

    from app.workers.tasks import check_subscription_posts
    from app.workers.celery_app import QUEUE_HEAVY
    check_subscription_posts.apply_async(args=[s.id], queue=QUEUE_HEAVY)
    return {"status": "queued"}
