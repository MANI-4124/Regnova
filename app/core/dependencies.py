from collections.abc import Generator

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.database import DatabaseState
from app.core.settings import Settings


def get_database(request: Request) -> DatabaseState:
    return request.app.state.database


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_db_session(
    database: DatabaseState = Depends(get_database),
) -> Generator[Session, None, None]:
    session = database.session_factory()

    try:
        yield session
    finally:
        session.close()