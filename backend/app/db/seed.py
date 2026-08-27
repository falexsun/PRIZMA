import asyncio

from sqlalchemy import select

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


async def seed() -> None:
    async with async_session_factory() as session:
        existing_topics = (await session.execute(select(Topic.name))).scalars().all()
        for name in TOPICS:
            if name not in existing_topics:
                session.add(Topic(name=name))

        existing_logins = (await session.execute(select(User.login))).scalars().all()

        if ADMIN["login"] not in existing_logins:
            session.add(
                User(
                    login=ADMIN["login"],
                    password_hash=hash_password(ADMIN["password"]),
                    org_name=ADMIN["org_name"],
                    department=ADMIN["department"],
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

        await session.commit()
    print("Seed complete.")


if __name__ == "__main__":
    asyncio.run(seed())
