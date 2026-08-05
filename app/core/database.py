from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.settings import Settings, get_settings


class Base(DeclarativeBase):
    """
    Base class for all SQLAlchemy models.
    """

    pass


@dataclass(frozen=True, slots=True)
class DatabaseState:
    """
    Stores the database engine and session factory.
    """

    engine: Engine
    session_factory: sessionmaker[Session]


def create_engine_from_settings(settings: Settings) -> Engine:
    """
    Create a SQLAlchemy engine.
    """

    return create_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_pre_ping=True,
    )


def create_session_factory(
    engine: Engine,
) -> sessionmaker[Session]:
    """
    Create the SQLAlchemy session factory.
    """

    return sessionmaker(
        bind=engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


def build_database(
    settings: Settings | None = None,
) -> DatabaseState:
    """
    Build the application's database state.
    """

    settings = settings or get_settings()

    engine = create_engine_from_settings(settings)

    session_factory = create_session_factory(engine)

    return DatabaseState(
        engine=engine,
        session_factory=session_factory,
    )