from collections.abc import Generator
from contextlib import contextmanager

from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    database_url: str = "postgresql+psycopg://rag:rag@localhost:5432/rag_platform"


def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or DatabaseSettings().database_url
    return create_engine(url)


def get_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
