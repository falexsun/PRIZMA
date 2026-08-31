import io
from datetime import datetime, timezone

import openpyxl
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import Link, LinkMetrics, Message, MessageMetricsSnapshot, Topic, User
from app.models.enums import FetchStatus, UserRole
from app.models.fetch_job import FetchJob
from app.parsers.base import ParserNotFoundError, ParserUnavailableError
from app.parsers.registry import get_parser
from app.schemas.message import MAX_LINKS, MessageCreate, MessageDetail, MessageListItem, MessageListResponse, MessageUpdate
from app.services import config_service
from app.services.link_file_parser import parse_links_file
from app.services.si import calc_si
from app.services.snapshot import recompute_message_snapshot_async
from app.services.url_normalize import UnsupportedUrlError, normalize_url
from app.services.ws_publish import publish_message_update

MAX_UPLOAD_SIZE_BYTES = 10 * 1024 * 1024  # 10 MB

router = APIRouter(tags=["messages"], dependencies=[Depends(get_current_user)])


def _visible_messages_query(user: User):
    query = select(Message).options(
        selectinload(Message.topics),
        selectinload(Message.links).selectinload(Link.metrics_history),
        selectinload(Message.snapshot),
    )
    if user.role != UserRole.admin:
        query = query.where(Message.user_id == user.id)
    return query


def _visible_messages_list_query(user: User):
    query = select(Message).options(
        selectinload(Message.topics),
        selectinload(Message.snapshot),
    )
    if user.role != UserRole.admin:
        query = query.where(Message.user_id == user.id)
    return query


async def _get_owned_message(message_id: int, user: User, db: AsyncSession) -> Message:
    query = _visible_messages_query(user).where(Message.id == message_id)
    message = (await db.execute(query)).scalar_one_or_none()
    if message is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
    return message


def _add_links(message: Message, raw_urls: list[str]) -> None:
    existing_normalized = {link.url_normalized for link in message.links}
    for raw_url in raw_urls:
        try:
            normalized, platform = normalize_url(raw_url)
        except UnsupportedUrlError:
            continue
        if normalized in existing_normalized:
            continue
        existing_normalized.add(normalized)
        link = Link(url_raw=raw_url, url_normalized=normalized, platform=platform)
        message.links.append(link)


def _to_detail(message: Message) -> MessageDetail:
    snapshot = message.snapshot
    links_out = []
    for link in message.links:
        latest = max(link.metrics_history, key=lambda m: m.fetched_at, default=None)
        links_out.append({
            "id": link.id,
            "url_raw": link.url_raw,
            "url_normalized": link.url_normalized,
            "platform": link.platform,
            "created_at": link.created_at,
            "latest_metrics": latest,
        })

    return MessageDetail(
        id=message.id,
        department=message.department,
        content_format=message.content_format,
        title=message.title,
        tone=message.tone,
        topics=message.topics,
        links=links_out,
        si_total=snapshot.si_total if snapshot else 0,
        views_total=snapshot.views_total if snapshot else 0,
        links_count=snapshot.links_count if snapshot else len(message.links),
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


def _to_list_item(message: Message) -> MessageListItem:
    snapshot = message.snapshot
    return MessageListItem(
        id=message.id,
        department=message.department,
        content_format=message.content_format,
        title=message.title,
        tone=message.tone,
        topics=message.topics,
        si_total=snapshot.si_total if snapshot else 0,
        views_total=snapshot.views_total if snapshot else 0,
        created_at=message.created_at,
        updated_at=message.updated_at,
    )


@router.get("/messages", response_model=MessageListResponse)
async def list_messages(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    department: str | None = None,
    tone: str | None = None,
    search: str | None = None,
    topic_id: int | None = None,
) -> MessageListResponse:
    query = _visible_messages_list_query(user)
    count_query = select(func.count(func.distinct(Message.id)))
    if user.role != UserRole.admin:
        count_query = count_query.where(Message.user_id == user.id)

    if department:
        query = query.where(Message.department == department)
        count_query = count_query.where(Message.department == department)
    if tone:
        query = query.where(Message.tone == tone)
        count_query = count_query.where(Message.tone == tone)
    if search:
        query = query.where(Message.title.ilike(f"%{search}%"))
        count_query = count_query.where(Message.title.ilike(f"%{search}%"))
    if topic_id:
        query = query.join(Message.topics).where(Topic.id == topic_id)
        count_query = count_query.join(Message.topics).where(Topic.id == topic_id)

    query = query.order_by(Message.created_at.desc()).offset((page - 1) * page_size).limit(page_size)

    total = int((await db.execute(count_query)).scalar_one() or 0)
    messages = (await db.execute(query)).scalars().unique().all()
    return MessageListResponse(
        items=[_to_list_item(m) for m in messages],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.post("/messages", response_model=MessageDetail, status_code=status.HTTP_201_CREATED)
async def create_message(
    payload: MessageCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageDetail:
    topics = []
    if payload.topic_ids:
        topics = list((await db.execute(select(Topic).where(Topic.id.in_(payload.topic_ids)))).scalars().all())

    message = Message(
        user_id=user.id,
        department=payload.department,
        tone=payload.tone,
        title=payload.title,
        content_format=payload.content_format,
        topics=topics,
    )
    _add_links(message, payload.links)
    # Capture the Link objects now: when zero links are added, message.links
    # is a freshly-initialized (never-appended-to) collection that SQLAlchemy
    # expires after flush() assigns the parent's PK, and re-accessing it then
    # requires a lazy SELECT that crashes outside an async context.
    created_links = list(message.links)

    if payload.links and not created_links:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "None of the provided links matched a supported platform (vk, telegram, youtube, tiktok, instagram, dzen, max)",
        )

    db.add(message)
    await db.flush()

    db.add(MessageMetricsSnapshot(message_id=message.id, links_count=len(created_links)))
    for link in created_links:
        db.add(FetchJob(link_id=link.id))

    await db.commit()
    message = await _get_owned_message(message.id, user, db)
    return _to_detail(message)


@router.get("/messages/{message_id}", response_model=MessageDetail)
async def get_message(
    message_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> MessageDetail:
    message = await _get_owned_message(message_id, user, db)
    return _to_detail(message)


@router.get("/messages/{message_id}/metrics/export")
async def export_message_metrics(
    message_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> StreamingResponse:
    message = await _get_owned_message(message_id, user, db)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Метрики"
    sheet.append(
        [
            "URL",
            "Лайки",
            "Репосты",
            "Комментарии",
            "Сохранения",
            "Просмотры",
            "Si",
            "Обновлено",
            "Хэштеги",
        ]
    )

    for link in message.links:
        latest = max(link.metrics_history, key=lambda m: m.fetched_at, default=None)
        is_instagram_reel = (
            (link.platform.value if hasattr(link.platform, "value") else str(link.platform)) == "instagram"
            and "/reel/" in link.url_normalized
        )
        reposts = "" if latest and is_instagram_reel and latest.reposts == 0 else (latest.reposts if latest else "")
        sheet.append(
            [
                link.url_raw,
                latest.likes if latest else "",
                reposts,
                latest.comments if latest else "",
                latest.saves if latest else "",
                latest.views if latest else "",
                latest.si if latest else "",
                latest.fetched_at.replace(tzinfo=None) if latest and latest.fetched_at else "",
                link.hashtags or "",
            ]
        )

    for column in sheet.columns:
        max_length = max(len(str(cell.value or "")) for cell in column)
        sheet.column_dimensions[column[0].column_letter].width = min(max(max_length + 2, 10), 60)

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=message_{message_id}_metrics.xlsx"},
    )


@router.patch("/messages/{message_id}", response_model=MessageDetail)
async def update_message(
    message_id: int,
    payload: MessageUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageDetail:
    message = await _get_owned_message(message_id, user, db)

    if payload.department is not None:
        message.department = payload.department
    if payload.tone is not None:
        message.tone = payload.tone
    if payload.title is not None:
        message.title = payload.title
    if payload.content_format is not None:
        message.content_format = payload.content_format
    if payload.topic_ids is not None:
        topics = list((await db.execute(select(Topic).where(Topic.id.in_(payload.topic_ids)))).scalars().all())
        message.topics = topics

    if payload.link_ids_remove:
        message.links = [link for link in message.links if link.id not in set(payload.link_ids_remove)]

    if payload.links_add:
        new_links_start = len(message.links)
        _add_links(message, payload.links_add)
        await db.flush()
        for link in message.links[new_links_start:]:
            db.add(FetchJob(link_id=link.id))

    if message.snapshot:
        message.snapshot.links_count = len(message.links)

    await db.commit()
    message = await _get_owned_message(message_id, user, db)
    return _to_detail(message)


@router.delete("/messages/{message_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_message(
    message_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> None:
    message = await _get_owned_message(message_id, user, db)
    await db.delete(message)
    await db.commit()


@router.post("/messages/{message_id}/refresh-metrics", status_code=status.HTTP_202_ACCEPTED)
async def refresh_metrics(
    message_id: int, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
) -> dict[str, int]:
    message = await _get_owned_message(message_id, user, db)
    queued = 0
    now = datetime.now(timezone.utc)
    link_ids = [link.id for link in message.links]
    existing_jobs = (
        (
            await db.execute(
                select(FetchJob).where(
                    FetchJob.link_id.in_(link_ids),
                    FetchJob.status.in_(
                        [FetchStatus.pending, FetchStatus.in_progress, FetchStatus.unavailable]
                    ),
                )
            )
        )
        .scalars()
        .all()
        if link_ids
        else []
    )
    jobs_by_link_id = {job.link_id: job for job in existing_jobs}

    for link in message.links:
        job = jobs_by_link_id.get(link.id)
        if job is None:
            db.add(FetchJob(link_id=link.id, next_run_at=now))
        else:
            job.status = FetchStatus.pending
            job.last_error = None
            job.next_run_at = now
        queued += 1
    await db.commit()
    return {"queued": queued}


@router.post("/messages/{message_id}/links/{link_id}/refresh-now")
async def refresh_link_now(
    message_id: int,
    link_id: int,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    message = await _get_owned_message(message_id, user, db)
    link = next((item for item in message.links if item.id == link_id), None)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")

    await config_service.refresh_settings(db)
    parser = get_parser(link.platform)
    try:
        metrics = await parser(link.url_normalized)
    except ParserNotFoundError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except ParserUnavailableError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    si = calc_si(metrics.likes, metrics.reposts, metrics.comments, metrics.saves)
    db.add(
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
    if metrics.hashtags:
        link.hashtags = ",".join(metrics.hashtags)

    snapshot = await recompute_message_snapshot_async(db, message.id)
    await db.commit()

    publish_message_update(
        message.id,
        message.user_id,
        {
            "message_id": message.id,
            "si_total": snapshot.si_total,
            "views_total": snapshot.views_total,
            "link_id": link.id,
            "link_si": si,
            "refresh_mode": "immediate",
        },
    )
    return {
        "link_id": link.id,
        "likes": metrics.likes,
        "reposts": metrics.reposts,
        "comments": metrics.comments,
        "saves": metrics.saves,
        "views": metrics.views,
        "si": si,
    }


@router.post("/messages/{message_id}/links/upload", response_model=MessageDetail)
async def upload_links_file(
    message_id: int,
    file: UploadFile,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> MessageDetail:
    message = await _get_owned_message(message_id, user, db)

    content = await file.read()
    if len(content) > MAX_UPLOAD_SIZE_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File too large: maximum size is {MAX_UPLOAD_SIZE_BYTES // (1024 * 1024)} MB",
        )
    try:
        urls = parse_links_file(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))

    if len(message.links) + len(urls) > MAX_LINKS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Too many links: max {MAX_LINKS}")

    new_links_start = len(message.links)
    _add_links(message, urls)
    await db.flush()
    for link in message.links[new_links_start:]:
        db.add(FetchJob(link_id=link.id))

    if message.snapshot:
        message.snapshot.links_count = len(message.links)

    await db.commit()
    message = await _get_owned_message(message_id, user, db)
    return _to_detail(message)
