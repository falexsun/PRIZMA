from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import settings

sync_engine = create_engine(settings.database_url.replace("postgresql+asyncpg", "postgresql+psycopg2"))
SyncSessionLocal = sessionmaker(bind=sync_engine)
