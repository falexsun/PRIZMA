import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import Link, Message, User, VKGroup, VKGroupPost
from app.models.enums import Tone
from app.schemas.vk_group import VKGroupCreate, VKGroupOut, VKGroupPostOut, VKGroupUpdate
from app.services import config_service

VK_API_BASE = "https://api.vk.com/method"
VK_API_VERSION = "5.199"

router = APIRouter(prefix="/vk-groups", tags=["vk-groups"], dependencies=[Depends(get_current_user)])


def _parse_vk_group_url(url: str) -> str | None:
    """Extract group identifier from VK URL or screen name."""
    url = url.strip()
    # Match patterns like:
    # https://vk.com/public12345
    # https://vk.com/club12345
    # https://vk.com/group_screen_name
    # public12345
    # club12345
    # screen_name
    patterns = [
        r"(?:https?://)?(?:www\.)?vk\.com/(?:public|club)(\d+)",
        r"(?:https?://)?(?:www\.)?vk\.com/([a-zA-Z][a-zA-Z0-9_.]+)",
        r"^(public|club)(\d+)$",
        r"^([a-zA-Z][a-zA-Z0-9_.]+)$",
    ]
    for pattern in patterns:
        match = re.match(pattern, url, re.IGNORECASE)
        if match:
            groups = match.groups()
            if len(groups) == 2 and groups[0] in ("public", "club"):
                return groups[1]  # Return numeric ID
            return groups[0]  # Return screen name
    return None


async def _resolve_vk_group(token: str, group_identifier: str) -> dict:
    """Resolve VK group info using API."""
    params = {
        "access_token": token,
        "v": VK_API_VERSION,
    }

    # Try as group IDs
    if group_identifier.lstrip("-").isdigit():
        params["group_ids"] = group_identifier
    else:
        params["group_ids"] = group_identifier

    timeout = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.get(f"{VK_API_BASE}/groups.getById", params=params)
        response.raise_for_status()
        data = response.json()

    if "error" in data:
        error_msg = data["error"].get("error_msg", "Unknown VK API error")
        raise ValueError(f"VK API error: {error_msg}")

    groups = data.get("response", {}).get("groups", [])
    if not groups:
        raise ValueError(f"VK group not found: {group_identifier}")

    group = groups[0]
    return {
        "id": group["id"],
        "name": group.get("name", ""),
        "screen_name": group.get("screen_name", ""),
        "photo_url": group.get("photo_200", ""),
    }


@router.post("", response_model=VKGroupOut, status_code=status.HTTP_201_CREATED)
async def create_vk_group(
    payload: VKGroupCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VKGroupOut:
    await config_service.refresh_settings(db)
    vk_token = settings.vk_user_token or settings.vk_service_token
    if not vk_token:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "VK token is not configured")

    group_identifier = _parse_vk_group_url(payload.vk_group_url)
    if not group_identifier:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid VK group URL or identifier")

    try:
        group_info = await _resolve_vk_group(vk_token, group_identifier)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Failed to reach VK API: {exc}") from exc

    # Check if already exists
    existing = (
        await db.execute(select(VKGroup).where(VKGroup.vk_group_id == group_info["id"]))
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_409_CONFLICT, "VK group is already added")

    # Create a message for this group
    message = Message(
        user_id=user.id,
        department=user.department,
        tone=Tone.neutral,
        title=f"VK: {group_info['name']}",
        content_format="social_post",
    )
    db.add(message)
    await db.flush()

    now = datetime.now(timezone.utc)
    vk_group = VKGroup(
        user_id=user.id,
        message_id=message.id,
        vk_group_id=group_info["id"],
        name=group_info["name"],
        screen_name=group_info["screen_name"],
        photo_url=group_info["photo_url"],
        check_interval_minutes=payload.check_interval_minutes,
        backfill=payload.backfill,
        # When backfill=False, set last_checked_at=now to skip existing posts.
        # When backfill=True, leave it None so the task fetches all posts.
        last_checked_at=None if payload.backfill else now,
    )
    db.add(vk_group)
    await db.commit()
    await db.refresh(vk_group)

    return VKGroupOut(
        id=vk_group.id,
        vk_group_id=vk_group.vk_group_id,
        name=vk_group.name,
        screen_name=vk_group.screen_name,
        photo_url=vk_group.photo_url,
        is_active=vk_group.is_active,
        check_interval_minutes=vk_group.check_interval_minutes,
        last_checked_at=vk_group.last_checked_at,
        message_id=vk_group.message_id,
        posts_count=0,
        active_posts_count=0,
        created_at=vk_group.created_at,
    )


@router.get("", response_model=list[VKGroupOut])
async def list_vk_groups(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VKGroupOut]:
    query = select(VKGroup).options(selectinload(VKGroup.posts))
    if user.role.value != "admin":
        query = query.where(VKGroup.user_id == user.id)
    query = query.order_by(VKGroup.created_at.desc())

    groups = (await db.execute(query)).scalars().unique().all()
    now = datetime.now(timezone.utc)

    result = []
    for g in groups:
        posts_count = len(g.posts)
        active_count = sum(
            1 for p in g.posts if (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() < 86400
        )
        result.append(
            VKGroupOut(
                id=g.id,
                vk_group_id=g.vk_group_id,
                name=g.name,
                screen_name=g.screen_name,
                photo_url=g.photo_url,
                is_active=g.is_active,
                check_interval_minutes=g.check_interval_minutes,
                last_checked_at=g.last_checked_at,
                message_id=g.message_id,
                posts_count=posts_count,
                active_posts_count=active_count,
                created_at=g.created_at,
            )
        )
    return result


@router.get("/{group_id}", response_model=VKGroupOut)
async def get_vk_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VKGroupOut:
    g = (
        await db.execute(
            select(VKGroup).options(selectinload(VKGroup.posts)).where(VKGroup.id == group_id)
        )
    ).scalar_one_or_none()
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")
    if user.role.value != "admin" and g.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")

    now = datetime.now(timezone.utc)
    posts_count = len(g.posts)
    active_count = sum(
        1 for p in g.posts if (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() < 86400
    )
    return VKGroupOut(
        id=g.id,
        vk_group_id=g.vk_group_id,
        name=g.name,
        screen_name=g.screen_name,
        photo_url=g.photo_url,
        is_active=g.is_active,
        check_interval_minutes=g.check_interval_minutes,
        last_checked_at=g.last_checked_at,
        message_id=g.message_id,
        posts_count=posts_count,
        active_posts_count=active_count,
        created_at=g.created_at,
    )


@router.patch("/{group_id}", response_model=VKGroupOut)
async def update_vk_group(
    group_id: int,
    payload: VKGroupUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> VKGroupOut:
    g = (
        await db.execute(
            select(VKGroup).options(selectinload(VKGroup.posts)).where(VKGroup.id == group_id)
        )
    ).scalar_one_or_none()
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")
    if user.role.value != "admin" and g.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")

    if payload.is_active is not None:
        g.is_active = payload.is_active
    if payload.check_interval_minutes is not None:
        g.check_interval_minutes = payload.check_interval_minutes

    await db.commit()
    await db.refresh(g)

    now = datetime.now(timezone.utc)
    posts_count = len(g.posts)
    active_count = sum(
        1 for p in g.posts if (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() < 86400
    )
    return VKGroupOut(
        id=g.id,
        vk_group_id=g.vk_group_id,
        name=g.name,
        screen_name=g.screen_name,
        photo_url=g.photo_url,
        is_active=g.is_active,
        check_interval_minutes=g.check_interval_minutes,
        last_checked_at=g.last_checked_at,
        message_id=g.message_id,
        posts_count=posts_count,
        active_posts_count=active_count,
        created_at=g.created_at,
    )


@router.delete("/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vk_group(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> None:
    g = (await db.execute(select(VKGroup).where(VKGroup.id == group_id))).scalar_one_or_none()
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")
    if user.role.value != "admin" and g.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")

    await db.delete(g)
    await db.commit()


@router.get("/{group_id}/posts", response_model=list[VKGroupPostOut])
async def list_vk_group_posts(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> list[VKGroupPostOut]:
    g = (await db.execute(select(VKGroup).where(VKGroup.id == group_id))).scalar_one_or_none()
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")
    if user.role.value != "admin" and g.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")

    posts = (
        await db.execute(
            select(VKGroupPost)
            .where(VKGroupPost.vk_group_id == group_id)
            .order_by(VKGroupPost.post_created_at.desc())
        )
    ).scalars().all()

    now = datetime.now(timezone.utc)
    result = []
    for p in posts:
        age_hours = (now - p.post_created_at.replace(tzinfo=timezone.utc)).total_seconds() / 3600
        is_tracking = age_hours < 24 and p.link_id is not None
        result.append(
            VKGroupPostOut(
                id=p.id,
                post_external_id=p.post_external_id,
                link_id=p.link_id,
                post_created_at=p.post_created_at,
                first_seen_at=p.first_seen_at,
                is_tracking=is_tracking,
            )
        )
    return result


@router.post("/{group_id}/check-now", status_code=status.HTTP_202_ACCEPTED)
async def check_group_now(
    group_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    g = (await db.execute(select(VKGroup).where(VKGroup.id == group_id))).scalar_one_or_none()
    if not g:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")
    if user.role.value != "admin" and g.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "VK group not found")

    from app.workers.tasks import check_vk_group_posts

    check_vk_group_posts.delay(g.id)
    return {"status": "queued"}
