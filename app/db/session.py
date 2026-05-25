from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def create_db_engine(database_url: str) -> Engine:
    if not database_url:
        raise RuntimeError("DATABASE_URL is required")
    connect_args = {}
    if database_url.startswith("postgresql+psycopg"):
        connect_args["prepare_threshold"] = None
    return create_engine(database_url, pool_pre_ping=True, connect_args=connect_args)


def create_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)
