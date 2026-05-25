from collections.abc import Generator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def create_db_engine(database_url: str) -> Engine:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    database_url = normalize_database_url(database_url)
    connect_args = {}
    if database_url.startswith("postgresql+psycopg"):
        connect_args["prepare_threshold"] = None
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def create_session_factory(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=create_db_engine(database_url), expire_on_commit=False)


def get_session() -> Generator[Session, None, None]:
    settings: Settings = get_settings()
    factory = create_session_factory(settings.database_url)
    with factory() as session:
        yield session
