from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from app.modules.organization.router import router as organization_router
from fastapi import FastAPI



from app.core.database import build_database
from app.core.settings import get_settings

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """
    Application startup and shutdown.
    """

    settings = get_settings()

    app.state.settings = settings
    app.state.database = build_database(settings)

    yield

    app.state.database.engine.dispose()


def create_app() -> FastAPI:
    """
    Create the FastAPI application.
    """

    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        lifespan=lifespan,
    )

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "message": "Welcome to Regnova"
        }
    app.include_router(organization_router)
    return app


app = create_app()