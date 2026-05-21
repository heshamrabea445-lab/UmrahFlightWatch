from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


def create_db_engine(database_url: str) -> Engine:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    return create_engine(database_url, pool_pre_ping=True)


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=create_db_engine(database_url), expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    settings: Settings = get_settings()
    factory = create_session_factory(settings.database_url)
    with factory() as session:
        yield session
