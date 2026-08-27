from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.models import Link, LinkMetrics, MessageMetricsSnapshot


def recompute_message_snapshot(session: Session, message_id: int) -> MessageMetricsSnapshot:
    links = session.execute(select(Link).where(Link.message_id == message_id)).scalars().all()

    si_total = 0
    views_total = 0
    for link in links:
        latest = session.execute(
            select(LinkMetrics)
            .where(LinkMetrics.link_id == link.id)
            .order_by(LinkMetrics.fetched_at.desc(), LinkMetrics.id.desc())
            .limit(1)
        ).scalar_one_or_none()
        if latest:
            si_total += latest.si
            views_total += latest.views

    snapshot = session.get(MessageMetricsSnapshot, message_id)
    if snapshot is None:
        snapshot = MessageMetricsSnapshot(message_id=message_id)
        session.add(snapshot)

    snapshot.si_total = si_total
    snapshot.views_total = views_total
    snapshot.links_count = len(links)
    return snapshot


async def recompute_message_snapshot_async(session: AsyncSession, message_id: int) -> MessageMetricsSnapshot:
    links = (await session.execute(select(Link).where(Link.message_id == message_id))).scalars().all()

    si_total = 0
    views_total = 0
    for link in links:
        latest = (
            await session.execute(
                select(LinkMetrics)
                .where(LinkMetrics.link_id == link.id)
                .order_by(LinkMetrics.fetched_at.desc(), LinkMetrics.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        if latest:
            si_total += latest.si
            views_total += latest.views

    snapshot = await session.get(MessageMetricsSnapshot, message_id)
    if snapshot is None:
        snapshot = MessageMetricsSnapshot(message_id=message_id)
        session.add(snapshot)

    snapshot.si_total = si_total
    snapshot.views_total = views_total
    snapshot.links_count = len(links)
    return snapshot
