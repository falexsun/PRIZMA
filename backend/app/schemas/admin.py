from datetime import datetime

from pydantic import BaseModel

from app.models.enums import UserRole


class AdminUserCreate(BaseModel):
    login: str
    password: str
    org_name: str
    department: str
    role: UserRole = UserRole.org_user


class AdminUserUpdate(BaseModel):
    org_name: str | None = None
    department: str | None = None
    role: UserRole | None = None
    is_active: bool | None = None
    password: str | None = None


class AdminUserOut(BaseModel):
    id: int
    login: str
    org_name: str
    department: str
    role: UserRole
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class RatingRow(BaseModel):
    org_name: str
    messages_count: int
    si_total: int
    views_total: int
    avg_si: float
    rank: int


class DashboardSummary(BaseModel):
    top_orgs: list[RatingRow]
    platform_distribution: dict[str, int]
    tone_distribution: dict[str, int]
    top_messages: list[dict]


class SettingsMap(BaseModel):
    settings: dict[str, str | None]


class SettingsUpdate(BaseModel):
    settings: dict[str, str | None]


class MaxLoginStart(BaseModel):
    phone: str
    target_url: str = "https://max.ru/"


class MaxLoginCode(BaseModel):
    code: str


class MaxLoginPassword(BaseModel):
    password: str


class MaxLoginStatus(BaseModel):
    stage: str
    message: str


class TimeseriesPoint(BaseModel):
    date: str
    org_name: str
    si: int
