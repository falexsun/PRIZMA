from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import CONTENT_FORMATS, DEPARTMENTS
from app.core.deps import get_current_user
from app.db.session import get_db
from app.models import Topic
from app.schemas.topic import TopicOut

router = APIRouter(tags=["meta"], dependencies=[Depends(get_current_user)])


class TopicCreate(BaseModel):
    name: str


class TopicUpdate(BaseModel):
    name: str


@router.get("/topics", response_model=list[TopicOut])
async def list_topics(db: AsyncSession = Depends(get_db)) -> list[Topic]:
    return list((await db.execute(select(Topic).order_by(Topic.name))).scalars().all())


@router.post("/topics", response_model=TopicOut, status_code=status.HTTP_201_CREATED)
async def create_topic(payload: TopicCreate, db: AsyncSession = Depends(get_db)) -> Topic:
    existing = (await db.execute(select(Topic).where(Topic.name == payload.name))).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Topic already exists")
    topic = Topic(name=payload.name)
    db.add(topic)
    await db.commit()
    await db.refresh(topic)
    return topic


@router.patch("/topics/{topic_id}", response_model=TopicOut)
async def update_topic(topic_id: int, payload: TopicUpdate, db: AsyncSession = Depends(get_db)) -> Topic:
    topic = (await db.execute(select(Topic).where(Topic.id == topic_id))).scalar_one_or_none()
    if not topic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    existing = (await db.execute(select(Topic).where(Topic.name == payload.name, Topic.id != topic_id))).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Topic name already exists")
    topic.name = payload.name
    await db.commit()
    await db.refresh(topic)
    return topic


@router.delete("/topics/{topic_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_topic(topic_id: int, db: AsyncSession = Depends(get_db)) -> None:
    topic = (await db.execute(select(Topic).where(Topic.id == topic_id))).scalar_one_or_none()
    if not topic:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Topic not found")
    await db.delete(topic)
    await db.commit()


@router.get("/content-centers", response_model=list[str])
async def list_content_centers() -> list[str]:
    return DEPARTMENTS


@router.get("/content-formats", response_model=list[str])
async def list_content_formats() -> list[str]:
    return CONTENT_FORMATS
