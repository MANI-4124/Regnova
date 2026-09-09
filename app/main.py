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
from app.modules.requirement.router import router as requirement_router
from app.modules.requirement_version.router import router as requirement_version_router
from app.modules.rule.router import router as rule_router
from app.modules.rule_version.router import router as rule_version_router
from app.modules.regulatory_basis_release.router import router as regulatory_basis_release_router
from app.modules.product_market_state.router import router as product_market_state_router
from app.modules.assessment_run.router import router as assessment_run_router
from app.modules.finding.router import router as finding_router
from app.modules.state_snapshot.router import router as state_snapshot_router
from app.modules.market_readiness.router import router as market_readiness_router
from app.modules.internal_role_assignment.router import router as internal_role_assignment_router
from app.modules.notification.router import router as notification_router
from app.modules.content_review.router import router as content_review_router
from app.modules.document.router import router as document_router
from app.modules.document_version.router import router as document_version_router
from app.modules.evidence.router import router as evidence_router
from app.modules.audit.router import router as audit_router
from app.modules.export.router import router as export_router


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
    app.include_router(requirement_router)
    app.include_router(requirement_version_router)
    app.include_router(rule_router)
    app.include_router(rule_version_router)
    app.include_router(regulatory_basis_release_router)
    app.include_router(product_market_state_router)
    app.include_router(assessment_run_router)
    app.include_router(finding_router)
    app.include_router(state_snapshot_router)
    app.include_router(market_readiness_router)
    app.include_router(internal_role_assignment_router)
    app.include_router(notification_router)
    app.include_router(content_review_router)
    app.include_router(document_router)
    app.include_router(document_version_router)
    app.include_router(evidence_router)
    app.include_router(audit_router)
    app.include_router(export_router)
    register_exception_handlers(app)

    @app.get("/")
    def root() -> dict[str, str]:
        return {
            "message": "Welcome to Regnova",
        }

    return app


app = create_app()
