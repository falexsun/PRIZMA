import asyncio
import json
from pathlib import Path

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models import Topic, User
from app.models.enums import UserRole

TOPICS = [
    "Продукт A",
    "Продукт B",
    "Бренд",
    "Партнёрская программа",
    "Региональное событие",
    "Корпоративная новость",
]

ORG_USERS = [
    {"login": "org_north", "password": "org_north_pass", "org_name": "Северный филиал", "department": "Маркетинг"},
    {"login": "org_south", "password": "org_south_pass", "org_name": "Южный филиал", "department": "PR-отдел"},
    {"login": "org_east", "password": "org_east_pass", "org_name": "Восточный филиал", "department": "SMM"},
]

ADMIN = {"login": "admin", "password": "admin_pass", "org_name": "Головной офис", "department": "Управление"}

def _load_default_accounts() -> list[dict]:
    path = Path(settings.default_accounts_path)
    if not path.exists() or not path.is_file():
        return []

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(data, dict):
        data = data.get("users", [])
    if not isinstance(data, list):
        raise ValueError("default accounts file must contain a list or an object with a users list")

    accounts = []
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"default account #{idx} must be an object")
        if not item.get("login") or not item.get("password"):
            raise ValueError(f"default account #{idx} must include login and password")
        accounts.append(item)
    return accounts


def _role_from_value(value: str | None) -> UserRole:
    if value == UserRole.admin.value:
        return UserRole.admin
    return UserRole.org_user


async def seed() -> None:
    async with async_session_factory() as session:
        existing_topics = (await session.execute(select(Topic.name))).scalars().all()
        for name in TOPICS:
            if name not in existing_topics:
                session.add(Topic(name=name))

        existing_logins = (await session.execute(select(User.login))).scalars().all()

        admin_login = settings.initial_admin_login or ADMIN["login"]
        admin_password = settings.initial_admin_password or ADMIN["password"]
        admin_org_name = settings.initial_admin_org_name or ADMIN["org_name"]
        admin_department = settings.initial_admin_department or ADMIN["department"]

        if admin_login not in existing_logins:
            session.add(
                User(
                    login=admin_login,
                    password_hash=hash_password(admin_password),
                    org_name=admin_org_name,
                    department=admin_department,
                    role=UserRole.admin,
                )
            )

        for u in ORG_USERS:
            if u["login"] not in existing_logins:
                session.add(
                    User(
                        login=u["login"],
                        password_hash=hash_password(u["password"]),
                        org_name=u["org_name"],
                        department=u["department"],
                        role=UserRole.org_user,
                    )
                )
                existing_logins.append(u["login"])

        for account in _load_default_accounts():
            login = str(account["login"]).strip()
            if login in existing_logins:
                continue
            session.add(
                User(
                    login=login,
                    password_hash=hash_password(str(account["password"])),
                    org_name=str(account.get("org_name") or account.get("organization") or ""),
                    department=str(account.get("department") or ""),
                    role=_role_from_value(account.get("role")),
                    is_active=bool(account.get("is_active", True)),
                )
            )
            existing_logins.append(login)

        await session.commit()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
