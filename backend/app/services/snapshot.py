from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Link, LinkMetrics, MessageMetricsSnapshot


def recompute_message_snapshot(session: Session, message_id: int) -> MessageMetricsSnapshot:
    # Single efficient query: get sum of latest si and views for all links
    latest_subq = (
        select(
            LinkMetrics.link_id,
            func.max(LinkMetrics.fetched_at).label("max_fetched_at"),
        )
        .group_by(LinkMetrics.link_id)
        .subquery()
    )

    row = session.execute(
        select(
            func.coalesce(func.sum(LinkMetrics.si), 0),
            func.coalesce(func.sum(LinkMetrics.views), 0),
        )
        .select_from(Link)
        .join(latest_subq, latest_subq.c.link_id == Link.id)
        .join(
            LinkMetrics,
            (LinkMetrics.link_id == latest_subq.c.link_id)
            & (LinkMetrics.fetched_at == latest_subq.c.max_fetched_at),
        )
        .where(Link.message_id == message_id)
    ).one()

    links_count = session.execute(
        select(func.count()).select_from(Link).where(Link.message_id == message_id)
    ).scalar() or 0

    snapshot = session.get(MessageMetricsSnapshot, message_id)
    if snapshot is None:
        snapshot = MessageMetricsSnapshot(message_id=message_id)
        session.add(snapshot)

    snapshot.si_total = row[0]
    snapshot.views_total = row[1]
    snapshot.links_count = links_count
    return snapshot


async def recompute_message_snapshot_async(session: AsyncSession, message_id: int) -> MessageMetricsSnapshot:
    latest_subq = (
        select(
            LinkMetrics.link_id,
            func.max(LinkMetrics.fetched_at).label("max_fetched_at"),
        )
        .group_by(LinkMetrics.link_id)
        .subquery()
    )

    row = (await session.execute(
        select(
            func.coalesce(func.sum(LinkMetrics.si), 0),
            func.coalesce(func.sum(LinkMetrics.views), 0),
        )
        .select_from(Link)
        .join(latest_subq, latest_subq.c.link_id == Link.id)
        .join(
            LinkMetrics,
            (LinkMetrics.link_id == latest_subq.c.link_id)
            & (LinkMetrics.fetched_at == latest_subq.c.max_fetched_at),
        )
        .where(Link.message_id == message_id)
    )).one()

    links_count = (await session.execute(
        select(func.count()).select_from(Link).where(Link.message_id == message_id)
    )).scalar() or 0

    snapshot = await session.get(MessageMetricsSnapshot, message_id)
    if snapshot is None:
        snapshot = MessageMetricsSnapshot(message_id=message_id)
        session.add(snapshot)

    snapshot.si_total = row[0]
    snapshot.views_total = row[1]
    snapshot.links_count = links_count
    return snapshot
