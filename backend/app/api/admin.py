import io
import asyncio
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl
import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_admin
from app.core.security import hash_password
from app.db.session import get_db
from app.models import Link, LinkMetrics, Message, MessageMetricsSnapshot, User
from app.schemas.admin import (
    AdminUserCreate,
    AdminUserOut,
    AdminUserUpdate,
    DashboardSummary,
    MaxLoginCode,
    MaxLoginPassword,
    MaxLoginStart,
    MaxLoginStatus,
    RatingRow,
    SettingsMap,
    SettingsUpdate,
)
from app.services import config_service
from app.services.max_auth_service import MaxAuthError, max_auth_manager
from app.services.proxy import normalize_proxy

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


PLATFORM_CHECK_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _exception_message(exc: Exception) -> str:
    message = str(exc).strip()
    return message or exc.__class__.__name__


def _platform_urls(item: dict) -> list[str]:
    if urls := item.get("urls"):
        return list(urls)
    if item["id"] == "youtube":
        return ["https://www.youtube.com/generate_204", "https://www.youtube.com"]
    if item["id"] == "telegram":
        return ["https://telegram.org", "https://t.me"]
    return [item["url"]]


async def _check_http_route(item: dict, proxy: str | None) -> tuple[bool, str]:
    timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
    errors: list[str] = []
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        proxy=proxy,
        trust_env=False,
        headers=PLATFORM_CHECK_HEADERS,
    ) as client:
        for url in _platform_urls(item):
            for method in ("HEAD", "GET"):
                try:
                    response = await client.request(method, url)
                    if response.status_code < 500:
                        return True, f"{method} {response.status_code}"
                    errors.append(f"{method} {response.status_code}")
                    break
                except Exception as exc:
                    errors.append(f"{method} {_exception_message(exc)}")
    return False, "; ".join(errors[-3:]) or "No response"


async def _check_platform_item(item: dict, vk_token: str | None, max_session: dict | None) -> dict:
    primary_ok, primary_message = await _check_http_route(item, item["proxy"])
    route = item["route"]
    reachable = primary_ok
    message = primary_message if primary_ok else f"Network check failed: {primary_message}"

    if not primary_ok and item["proxy"]:
        direct_ok, direct_message = await _check_http_route(item, None)
        if direct_ok:
            reachable = True
            route = "direct"
            message = f"{direct_message}; configured proxy failed: {primary_message}"
        else:
            message = f"Network check failed: {primary_message}; direct failed: {direct_message}"

    if item["id"] == "vk_video" and not vk_token:
        message = f"{message}; VK token is not configured"
    if item["id"] == "max" and not (max_session or {}).get("valid"):
        message = f"{message}; MAX session is not active"

    return {
        "id": item["id"],
        "label": item["label"],
        "configured": item["configured"],
        "reachable": reachable,
        "route": route,
        "requirement": item["requirement"],
        "message": message,
    }


def _single_platform_item(platform_id: str, values: dict, max_session: dict | None) -> dict | None:
    non_ru_proxy = normalize_proxy(values.get("non_ru_proxy"))
    ru_proxy = normalize_proxy(values.get("ru_proxy"))
    vk_token = values.get("vk_user_token") or values.get("vk_service_token")
    items = {
        "vk": {
            "id": "vk",
            "label": "VK posts",
            "url": "https://vk.ru",
            "proxy": None,
            "route": "direct",
            "requirement": "Direct access; VK token improves accuracy.",
            "configured": True,
        },
        "vk_video": {
            "id": "vk_video",
            "label": "VK video",
            "url": "https://vkvideo.ru",
            "proxy": None,
            "route": "direct",
            "requirement": "Supports vk.com/video, vk.com/clip and vkvideo.ru links; VK token is required for accurate video.get metrics.",
            "configured": bool(vk_token),
        },
        "telegram": {
            "id": "telegram",
            "label": "Telegram",
            "url": "https://t.me",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Public preview page must be reachable directly or through NON-RU proxy.",
            "configured": True,
        },
        "youtube": {
            "id": "youtube",
            "label": "YouTube",
            "url": "https://www.youtube.com",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Uses public counters and yt-dlp fallback.",
            "configured": True,
        },
        "tiktok": {
            "id": "tiktok",
            "label": "TikTok",
            "url": "https://www.tiktok.com",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Must be reachable directly or through NON-RU proxy.",
            "configured": True,
        },
        "instagram": {
            "id": "instagram",
            "label": "Instagram",
            "url": "https://www.instagram.com",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Must be reachable directly or through NON-RU proxy.",
            "configured": True,
        },
        "dzen": {
            "id": "dzen",
            "label": "Dzen",
            "url": "https://dzen.ru",
            "proxy": ru_proxy,
            "route": "ru_proxy" if ru_proxy else "direct",
            "requirement": "Must be reachable directly or through RU proxy.",
            "configured": True,
        },
        "max": {
            "id": "max",
            "label": "MAX",
            "url": "https://max.ru",
            "proxy": None,
            "route": "direct",
            "requirement": "Active MAX session is required for metrics.",
            "configured": bool((max_session or {}).get("valid")),
        },
        "ok": {
            "id": "ok",
            "label": "OK",
            "url": "https://ok.ru",
            "proxy": ru_proxy,
            "route": "ru_proxy" if ru_proxy else "direct",
            "requirement": "Must be reachable directly or through RU proxy.",
            "configured": True,
        },
    }
    return items.get(platform_id)


def _period_start(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "7":
        return now - timedelta(days=7)
    if period == "30":
        return now - timedelta(days=30)
    if period == "90":
        return now - timedelta(days=90)
    return None


@router.get("/users", response_model=list[AdminUserOut])
async def list_users(db: AsyncSession = Depends(get_db)) -> list[User]:
    return list((await db.execute(select(User).order_by(User.created_at.desc()))).scalars().all())


@router.post("/users", response_model=AdminUserOut, status_code=status.HTTP_201_CREATED)
async def create_user(payload: AdminUserCreate, db: AsyncSession = Depends(get_db)) -> User:
    existing = (await db.execute(select(User).where(User.login == payload.login))).scalar_one_or_none()
    if existing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Login already taken")

    user = User(
        login=payload.login,
        password_hash=hash_password(payload.password),
        org_name=payload.org_name,
        department=payload.department,
        role=payload.role,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=AdminUserOut)
async def update_user(
    user_id: int, payload: AdminUserUpdate, db: AsyncSession = Depends(get_db)
) -> User:
    user = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

    if payload.org_name is not None:
        user.org_name = payload.org_name
    if payload.department is not None:
        user.department = payload.department
    if payload.role is not None:
        user.role = payload.role
    if payload.is_active is not None:
        user.is_active = payload.is_active
    if payload.password:
        user.password_hash = hash_password(payload.password)

    await db.commit()
    await db.refresh(user)
    return user


async def _rating_rows(db: AsyncSession, period: str) -> list[RatingRow]:
    query = (
        select(
            User.org_name,
            func.count(Message.id).label("messages_count"),
            func.coalesce(func.sum(MessageMetricsSnapshot.si_total), 0).label("si_total"),
            func.coalesce(func.sum(MessageMetricsSnapshot.views_total), 0).label("views_total"),
        )
        .join(Message, Message.user_id == User.id)
        .join(MessageMetricsSnapshot, MessageMetricsSnapshot.message_id == Message.id, isouter=True)
        .group_by(User.org_name)
        .order_by(func.coalesce(func.sum(MessageMetricsSnapshot.si_total), 0).desc())
    )

    start = _period_start(period)
    if start is not None:
        query = query.where(Message.created_at >= start)

    rows = (await db.execute(query)).all()

    return [
        RatingRow(
            org_name=row.org_name,
            messages_count=row.messages_count,
            si_total=row.si_total,
            views_total=row.views_total,
            avg_si=round(row.si_total / row.messages_count, 1) if row.messages_count else 0.0,
            rank=idx + 1,
        )
        for idx, row in enumerate(rows)
    ]


@router.get("/rating", response_model=list[RatingRow])
async def rating(period: str = Query("30"), db: AsyncSession = Depends(get_db)) -> list[RatingRow]:
    return await _rating_rows(db, period)


@router.get("/rating/export")
async def rating_export(period: str = Query("30"), db: AsyncSession = Depends(get_db)) -> StreamingResponse:
    rows = await _rating_rows(db, period)

    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Рейтинг"
    sheet.append(["Место", "Регион", "Кол-во инфоповодов", "Σ Si", "Σ просмотров", "Средний Si"])
    for row in rows:
        sheet.append([row.rank, row.org_name, row.messages_count, row.si_total, row.views_total, row.avg_si])

    buffer = io.BytesIO()
    workbook.save(buffer)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=rating_{period}.xlsx"},
    )


@router.get("/dashboard/summary", response_model=DashboardSummary)
async def dashboard_summary(period: str = Query("30"), db: AsyncSession = Depends(get_db)) -> DashboardSummary:
    top_orgs = (await _rating_rows(db, period))[:10]

    start = _period_start(period)
    platform_query = (
        select(Link.platform, func.count(Link.id))
        .join(Message, Message.id == Link.message_id)
        .group_by(Link.platform)
    )
    if start is not None:
        platform_query = platform_query.where(Message.created_at >= start)
    platform_rows = (await db.execute(platform_query)).all()
    platform_distribution = {platform.value: count for platform, count in platform_rows}

    tone_query = select(Message.tone, func.count(Message.id)).group_by(Message.tone)
    if start is not None:
        tone_query = tone_query.where(Message.created_at >= start)
    tone_rows = (await db.execute(tone_query)).all()
    tone_distribution = {tone.value: count for tone, count in tone_rows}

    week_start = datetime.now(timezone.utc) - timedelta(days=7)
    top_messages_query = (
        select(Message.id, Message.title, MessageMetricsSnapshot.si_total)
        .join(MessageMetricsSnapshot, MessageMetricsSnapshot.message_id == Message.id)
        .where(Message.created_at >= week_start)
        .order_by(MessageMetricsSnapshot.si_total.desc())
        .limit(10)
    )
    top_messages_rows = (await db.execute(top_messages_query)).all()
    top_messages = [{"id": r.id, "title": r.title, "si_total": r.si_total} for r in top_messages_rows]

    return DashboardSummary(
        top_orgs=top_orgs,
        platform_distribution=platform_distribution,
        tone_distribution=tone_distribution,
        top_messages=top_messages,
    )


@router.get("/dashboard/timeseries")
async def dashboard_timeseries(period: str = Query("30"), db: AsyncSession = Depends(get_db)) -> list[dict]:
    start = _period_start(period) or (datetime.now(timezone.utc) - timedelta(days=30))

    query = (
        select(
            func.date(LinkMetrics.fetched_at).label("day"),
            User.org_name,
            func.sum(LinkMetrics.si).label("si"),
        )
        .join(Link, Link.id == LinkMetrics.link_id)
        .join(Message, Message.id == Link.message_id)
        .join(User, User.id == Message.user_id)
        .where(LinkMetrics.fetched_at >= start)
        .group_by("day", User.org_name)
        .order_by("day")
    )
    rows = (await db.execute(query)).all()

    return [{"date": str(row.day), "org_name": row.org_name, "si": row.si} for row in rows]


@router.get("/settings", response_model=SettingsMap)
async def get_settings(db: AsyncSession = Depends(get_db)) -> SettingsMap:
    await config_service.refresh_settings(db)
    return SettingsMap(settings=await config_service.load_settings(db))


@router.put("/settings", response_model=SettingsMap)
async def update_settings(payload: SettingsUpdate, db: AsyncSession = Depends(get_db)) -> SettingsMap:
    await config_service.set_settings_bulk(db, payload.settings)
    await config_service.refresh_settings(db)
    return SettingsMap(settings=await config_service.load_settings(db))


@router.get("/settings/proxy-status")
async def proxy_status(db: AsyncSession = Depends(get_db)) -> dict:
    values = await config_service.load_settings(db)

    async def check_proxy(key: str) -> dict:
        raw = values.get(key)
        proxy = normalize_proxy(raw)
        if not proxy:
            return {"configured": False, "valid": False, "message": "Not configured"}
        try:
            timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
            async with httpx.AsyncClient(timeout=timeout, proxy=proxy) as client:
                response = await client.get("https://api.ipify.org?format=json")
            response.raise_for_status()
            ip = response.json().get("ip") or "unknown ip"
            return {"configured": True, "valid": True, "message": f"Works, external IP: {ip}"}
        except Exception as exc:
            return {"configured": True, "valid": False, "message": f"Failed: {exc}"}

    return {
        "non_ru_proxy": await check_proxy("non_ru_proxy"),
        "ru_proxy": await check_proxy("ru_proxy"),
    }


@router.get("/settings/vk-token-status")
async def vk_token_status(db: AsyncSession = Depends(get_db)) -> dict:
    values = await config_service.load_settings(db)
    token_type = "user" if values.get("vk_user_token") else "service" if values.get("vk_service_token") else None
    token = values.get("vk_user_token") or values.get("vk_service_token")
    if not token:
        return {"configured": False, "valid": False, "type": None, "message": "Not configured"}

    try:
        timeout = httpx.Timeout(connect=5.0, read=8.0, write=5.0, pool=5.0)
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(
                "https://api.vk.com/method/users.get",
                params={"access_token": token, "v": "5.199"},
            )
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        return {"configured": True, "valid": False, "type": token_type, "message": f"Request failed: {exc}"}

    if "error" in data:
        error = data["error"]
        return {
            "configured": True,
            "valid": False,
            "type": token_type,
            "message": error.get("error_msg") or "VK token error",
        }

    return {"configured": True, "valid": True, "type": token_type, "message": "Token works"}


@router.get("/settings/platform-status")
async def platform_status(db: AsyncSession = Depends(get_db)) -> list[dict]:
    values = await config_service.load_settings(db)
    non_ru_proxy = normalize_proxy(values.get("non_ru_proxy"))
    ru_proxy = normalize_proxy(values.get("ru_proxy"))
    vk_token = values.get("vk_user_token") or values.get("vk_service_token")
    max_session = await max_auth_manager.session_status()

    platforms = [
        {
            "id": "vk",
            "label": "VK посты",
            "url": "https://vk.ru",
            "proxy": None,
            "route": "direct",
            "requirement": "Работает напрямую; токен VK улучшает точность.",
            "configured": True,
        },
        {
            "id": "vk_video",
            "label": "VK видео и клипы",
            "url": "https://vkvideo.ru",
            "proxy": None,
            "route": "direct",
            "requirement": "Поддерживаются vk.com/video..., vk.com/clip... и vkvideo.ru/video-OWNER_ID_ITEM_ID; для точного сбора используется VK API video.get.",
            "configured": bool(vk_token),
        },
        {
            "id": "telegram",
            "label": "Telegram",
            "url": "https://t.me",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Публичная превью-страница работает напрямую или через NON-RU proxy.",
            "configured": True,
        },
        {
            "id": "youtube",
            "label": "YouTube",
            "url": "https://www.youtube.com",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Используется публичный счётчик и yt-dlp fallback.",
            "configured": True,
        },
        {
            "id": "tiktok",
            "label": "TikTok",
            "url": "https://www.tiktok.com",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Работает напрямую, если сеть открывает TikTok; иначе нужен NON-RU proxy.",
            "configured": True,
        },
        {
            "id": "instagram",
            "label": "Instagram",
            "url": "https://www.instagram.com",
            "proxy": non_ru_proxy,
            "route": "non_ru_proxy" if non_ru_proxy else "direct",
            "requirement": "Работает напрямую, если сеть открывает Instagram; иначе нужен NON-RU proxy.",
            "configured": True,
        },
        {
            "id": "dzen",
            "label": "Дзен",
            "url": "https://dzen.ru",
            "proxy": ru_proxy,
            "route": "ru_proxy" if ru_proxy else "direct",
            "requirement": "Работает напрямую или через RU proxy.",
            "configured": True,
        },
        {
            "id": "max",
            "label": "MAX",
            "url": "https://max.ru",
            "proxy": None,
            "route": "direct",
            "requirement": "Для метрик нужна активная сессия MAX.",
            "configured": bool(max_session.get("valid")),
        },
        {
            "id": "ok",
            "label": "Одноклассники",
            "url": "https://ok.ru",
            "proxy": ru_proxy,
            "route": "ru_proxy" if ru_proxy else "direct",
            "requirement": "Работает напрямую или через RU proxy.",
            "configured": True,
        },
    ]

    async def check(item: dict) -> dict:
        return await _check_platform_item(item, vk_token, max_session)

    return await asyncio.gather(*(check(item) for item in platforms))


@router.get("/settings/platform-status/{platform_id}")
async def single_platform_status(platform_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    values = await config_service.load_settings(db)
    max_session = await max_auth_manager.session_status() if platform_id == "max" else None
    item = _single_platform_item(platform_id, values, max_session)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform not found")
    vk_token = values.get("vk_user_token") or values.get("vk_service_token")
    return await _check_platform_item(item, vk_token, max_session)


@router.get("/settings/max-login", response_model=MaxLoginStatus)
async def max_login_status() -> MaxLoginStatus:
    return MaxLoginStatus(**max_auth_manager.status())


@router.get("/settings/max-session")
async def max_session_status() -> dict[str, str | bool]:
    return await max_auth_manager.session_status()


@router.post("/settings/max-login/start", response_model=MaxLoginStatus)
async def max_login_start(payload: MaxLoginStart) -> MaxLoginStatus:
    try:
        return MaxLoginStatus(**await max_auth_manager.start(payload.phone, payload.target_url))
    except MaxAuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/settings/max-login/code", response_model=MaxLoginStatus)
async def max_login_code(payload: MaxLoginCode) -> MaxLoginStatus:
    try:
        return MaxLoginStatus(**await max_auth_manager.submit_code(payload.code))
    except MaxAuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.post("/settings/max-login/password", response_model=MaxLoginStatus)
async def max_login_password(payload: MaxLoginPassword) -> MaxLoginStatus:
    try:
        return MaxLoginStatus(**await max_auth_manager.submit_password(payload.password))
    except MaxAuthError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc


@router.delete("/settings/max-login", response_model=MaxLoginStatus)
async def max_login_cancel() -> MaxLoginStatus:
    return MaxLoginStatus(**await max_auth_manager.cancel())


# --- VPN management ---

@router.get("/settings/vpn")
async def vpn_status() -> dict:
    """Check VPN configuration status."""
    from pathlib import Path

    vpn_dir = Path("vpn")
    config_exists = (vpn_dir / "wg0.conf").exists()

    return {
        "configured": config_exists,
        "config_path": str(vpn_dir / "wg0.conf"),
    }


@router.post("/settings/vpn/upload")
async def upload_vpn_config(file: UploadFile = File(...)) -> dict:
    """Upload WireGuard VPN configuration file."""
    if not file.filename:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No file provided")

    content = await file.read()
    if len(content) > 1024 * 1024:  # 1MB max
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "File too large")

    # Validate it looks like a WireGuard config
    text = content.decode("utf-8", errors="ignore")
    if "[Interface]" not in text or "[Peer]" not in text:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Invalid WireGuard config: must contain [Interface] and [Peer] sections",
        )

    vpn_dir = Path("vpn")
    vpn_dir.mkdir(parents=True, exist_ok=True)
    config_path = vpn_dir / "wg0.conf"
    config_path.write_bytes(content)

    return {
        "configured": True,
        "config_path": str(config_path),
        "message": "VPN config uploaded. Restart the vpn container to activate: docker compose restart vpn",
    }
