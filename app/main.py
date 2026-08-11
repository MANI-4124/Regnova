from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import app.models
from app.modules.user.router import router as user_router
from fastapi import FastAPI
from app.modules.auth.router import router as auth_router
from app.common.handlers import register_exception_handlers
from app.core.correlation import CorrelationIdMiddleware
from app.core.database import build_database
from app.core.settings import get_settings
from app.modules.product.router import router as product_router
from app.modules.product_version.router import router as product_version_router
from app.modules.organization.router import router as organization_router
from app.modules.role.router import router as role_router
from app.modules.source.router import router as source_router
from app.modules.source_version.router import router as source_version_router
from app.modules.source_location.router import router as source_location_router


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
    app.add_middleware(CorrelationIdMiddleware)
    app.include_router(organization_router)
    app.include_router(role_router)
    app.include_router(user_router)
    app.include_router(auth_router)
    app.include_router(product_router)
    app.include_router(product_version_router)
    app.include_router(source_router)
    app.include_router(source_version_router)
    app.include_router(source_location_router)
    register_exception_handlers(app)

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "message": "Welcome to Regnova",
        }

    return app


app = create_app()
