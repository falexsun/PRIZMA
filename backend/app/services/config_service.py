from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models import AppSetting

# Ключи, которые админ может менять через UI и которые воркер подхватывает runtime.
RUNTIME_SETTING_KEYS = {
    "vk_service_token",
    "vk_user_token",
    "youtube_api_key",
    "tiktok_rapidapi_key",
    "instagram_proxy",
    "max_headless_enabled",
    "max_session_path",
    "non_ru_proxy",
    "ru_proxy",
}


def _env_defaults() -> dict[str, str | None]:
    return {key: str(getattr(settings, key)) for key in RUNTIME_SETTING_KEYS}


def _apply_overrides(overrides: dict[str, str | None]) -> None:
    """Применить override-значения из БД к глобальному settings."""
    for key, value in overrides.items():
        if value is None:
            continue
        if key == "max_headless_enabled":
            value = value.lower() in {"true", "1", "yes", "on"}
        setattr(settings, key, value)


async def load_settings(db: AsyncSession) -> dict[str, str | None]:
    rows = (
        (await db.execute(select(AppSetting).where(AppSetting.key.in_(RUNTIME_SETTING_KEYS))))
        .scalars()
        .all()
    )
    db_values = {row.key: row.value for row in rows}
    return {**_env_defaults(), **db_values}


def load_settings_sync(db: Session) -> dict[str, str | None]:
    rows = db.execute(select(AppSetting).where(AppSetting.key.in_(RUNTIME_SETTING_KEYS))).scalars().all()
    db_values = {row.key: row.value for row in rows}
    return {**_env_defaults(), **db_values}


async def refresh_settings(db: AsyncSession) -> None:
    _apply_overrides(await load_settings(db))


def refresh_settings_sync(db: Session) -> None:
    _apply_overrides(load_settings_sync(db))


def get_setting(key: str, default: str | None = None) -> str | None:
    if key in RUNTIME_SETTING_KEYS:
        return getattr(settings, key, default)
    return default


async def set_setting(db: AsyncSession, key: str, value: str | None) -> None:
    existing = (
        await db.execute(select(AppSetting).where(AppSetting.key == key))
    ).scalar_one_or_none()
    if existing is None:
        db.add(AppSetting(key=key, value=value))
    else:
        existing.value = value
    await db.commit()


def set_setting_sync(db: Session, key: str, value: str | None) -> None:
    existing = db.execute(select(AppSetting).where(AppSetting.key == key)).scalar_one_or_none()
    if existing is None:
        db.add(AppSetting(key=key, value=value))
    else:
        existing.value = value
    db.commit()


async def set_settings_bulk(db: AsyncSession, values: dict[str, str | None]) -> None:
    """Обновить несколько настроек за один round-trip."""
    keys = [k for k in values.keys() if k in RUNTIME_SETTING_KEYS]
    if not keys:
        return

    existing_rows = (
        (await db.execute(select(AppSetting).where(AppSetting.key.in_(keys))))
        .scalars()
        .all()
    )
    existing_by_key = {row.key: row for row in existing_rows}

    for key, value in values.items():
        if key not in RUNTIME_SETTING_KEYS:
            continue
        row = existing_by_key.get(key)
        if row is None:
            db.add(AppSetting(key=key, value=value))
        else:
            row.value = value

    await db.commit()
