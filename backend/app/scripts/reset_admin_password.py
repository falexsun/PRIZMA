import asyncio
import os
import secrets

from sqlalchemy import select

from app.core.config import settings
from app.core.security import hash_password
from app.db.session import async_session_factory
from app.models import User
from app.models.enums import UserRole


async def main() -> None:
    login = os.getenv("RESET_ADMIN_LOGIN") or settings.initial_admin_login or "admin"
    password = os.getenv("RESET_ADMIN_PASSWORD") or secrets.token_urlsafe(16)

    async with async_session_factory() as session:
        user = (await session.execute(select(User).where(User.login == login))).scalar_one_or_none()
        if user is None:
            user = User(
                login=login,
                password_hash=hash_password(password),
                org_name=settings.initial_admin_org_name or "Head office",
                department=settings.initial_admin_department or "Administration",
                role=UserRole.admin,
                is_active=True,
            )
            session.add(user)
        else:
            user.password_hash = hash_password(password)
            user.role = UserRole.admin
            user.is_active = True

        await session.commit()

    print(f"Login: {login}")
    print(f"Password: {password}")


if __name__ == "__main__":
    asyncio.run(main())
