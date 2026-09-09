from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session

from app.core.dependencies import get_correlation_id, get_db_session, get_document_storage
from app.modules.auth.dependencies import get_current_active_user
from app.modules.rbac.dependencies import require_manager
from app.modules.user.models import User
from app.storage import DocumentStorage

from .schemas import ExportCreate, ExportResponse, InternalExportCreate
from .service import ExportService

router = APIRouter(
    prefix="/exports",
    tags=["Exports"],
)


def get_export_service(
    db: Session = Depends(get_db_session),
    storage: DocumentStorage = Depends(get_document_storage),
) -> ExportService:
    return ExportService(db, storage)


@router.get(
    "",
    response_model=list[ExportResponse],
)
def get_exports(
    product_market_state_id: UUID,
    current_user: User = Depends(require_manager),
    service: ExportService = Depends(get_export_service),
):
    return service.get_all(current_user.organization_id, product_market_state_id)


@router.get(
    "/{export_id}",
    response_model=ExportResponse,
)
def get_export(
    export_id: UUID,
    current_user: User = Depends(require_manager),
    service: ExportService = Depends(get_export_service),
):
    return service.get_by_id_for_customer(current_user.organization_id, export_id)


@router.post(
    "",
    response_model=ExportResponse,
)
def create_export(
    payload: ExportCreate,
    current_user: User = Depends(require_manager),
    correlation_id: str = Depends(get_correlation_id),
    service: ExportService = Depends(get_export_service),
):
    """
    Customer path - organization_id is always current_user.organization_id,
    never accepted from the request. ExportCreate's own Literal type
    already confines this to FINDINGS_CSV; see create_internal_export
    for EVIDENCE_PACK_JSON.
    """
    return service.generate_findings_csv(
        current_user.organization_id,
        payload.product_market_state_id,
        actor_user_id=current_user.id,
        correlation_id=correlation_id,
    )


@router.post(
    "/internal",
    response_model=ExportResponse,
)
def create_internal_export(
    payload: InternalExportCreate,
    current_user: User = Depends(get_current_active_user),
    correlation_id: str = Depends(get_correlation_id),
    service: ExportService = Depends(get_export_service),
):
    """
    The second deliberate, narrow exception to "organization_id is
    never client-supplied" - see CLAUDE.md "Deliberate organization_id
    exceptions" for the maintained list and every constraint that keeps
    it narrow. Deliberately gated by bare auth (get_current_active_user),
    not require_manager/a role-tier dependency - the real authorization
    (does this caller hold INTERNAL_REGULATORY clearance) needs data
    the router can't see cheaply, so it's checked in the service, the
    same "the check needs data the router can't see yet" precedent
    FindingService's transition methods and GET /audit-events/internal
    both already established.
    """
    export = service.generate_evidence_pack(
        caller_user_id=current_user.id,
        organization_id=payload.organization_id,
        product_market_state_id=payload.product_market_state_id,
        state_snapshot_id=payload.state_snapshot_id,
        correlation_id=correlation_id,
    )
    return export


@router.get(
    "/{export_id}/download",
)
def download_export(
    export_id: UUID,
    current_user: User = Depends(get_current_active_user),
    correlation_id: str = Depends(get_correlation_id),
    service: ExportService = Depends(get_export_service),
):
    """
    One shared download endpoint for both export types - see
    ExportService.resolve_for_download for why the authorization branch
    depends on data only the loaded row can supply. No signed/expiring
    URL: this IS the download link, protected the same way as every
    other authenticated endpoint in this codebase - get_current_active_user
    reloads the User row (and therefore role_id/is_active) fresh on
    every request, so a deactivated or revoked user's very next request
    fails here with no new revocation mechanism needed (AC-FR-14-02).
    Signed expiring URLs remain the deferred enhancement, shared with
    Documents' identical gap.
    """
    export, content = service.resolve_for_download(
        caller_user_id=current_user.id,
        caller_organization_id=current_user.organization_id,
        export_id=export_id,
        correlation_id=correlation_id,
    )

    extension = "csv" if export.content_type == "text/csv" else "json"
    filename = f"export_{export.id}.{extension}"

    return Response(
        content=content,
        media_type=export.content_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
