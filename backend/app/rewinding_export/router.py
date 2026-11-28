"""API RBE: reportes de Bobinas Refiladas para Exportación."""
import uuid
from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import Response as RawResponse
from app.auth.dependencies import current_user, require_permission
from app.auth.permissions import (
    REWINDING_EXPORT_CREATE, REWINDING_EXPORT_READ_OWN, REWINDING_EXPORT_READ_SECTOR,
    REWINDING_EXPORT_ANNUL, REWINDING_EXPORT_CLASSIFY_SOURCE,
)
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.rewinding_export import service
from app.rewinding_export.schemas import (
    AnnulIn, AnnulOut, ChildCreateIn, ChildCreatedOut, ClassificationIn, ClassificationOut,
    ClassifiableWorkOrderOut, DraftCreateIn, DraftCreatedOut, DraftHeaderIn, HistoryItemOut,
    LogicalRemoveIn, PackageCreateIn, PackageCreatedOut,
)
router = APIRouter(prefix="/api/rewinding-export", tags=["Bobinas refiladas para exportación"])

def _request_id():
    return str(uuid.uuid4())

def _sector_wide(user: AuthenticatedUser) -> bool:
    return user.can(REWINDING_EXPORT_READ_SECTOR)


@router.get("/mothers")
def eligible_mothers(response: Response,
                    pv_reference: str | None = Query(default=None, max_length=100),
                    article_code: str | None = Query(default=None, max_length=64),
                    user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                    connection=Depends(get_connection)):
    response.headers["Cache-Control"] = "private, no-store"
    return service.list_eligible_mothers(connection, sectors=user.sectors,
                                         pv_reference=pv_reference, article_code=article_code)

@router.post("/drafts", response_model=DraftCreatedOut, status_code=201)
def create_draft(body: DraftCreateIn, user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                 connection=Depends(get_connection)):
    report_id = service.create_draft(connection, actor_id=user.user_id, request_id=_request_id(),
                                     pv_reference=body.pv_reference, article_code=body.article_code, sectors=user.sectors)
    return {"id": report_id}

@router.patch("/drafts/{report_id}")
def update_draft(report_id: uuid.UUID, body: DraftHeaderIn,
                 user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                 connection=Depends(get_connection)):
    service.update_draft(connection, actor_id=user.user_id, request_id=_request_id(), report_id=report_id,
                         truck_number=body.truck_number, order_number=body.order_number, observations=body.observations)
    return {"id": report_id, "status": "draft"}

@router.post("/drafts/{report_id}/packages", response_model=PackageCreatedOut, status_code=201)
def add_package(report_id: uuid.UUID, body: PackageCreateIn,
                user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                connection=Depends(get_connection)):
    package_id = service.add_package(connection, actor_id=user.user_id, request_id=_request_id(),
                                     report_id=report_id, mother_capture_id=body.mother_capture_id, sectors=user.sectors)
    return {"id": package_id}

@router.post("/drafts/{report_id}/packages/{package_id}/children", response_model=ChildCreatedOut, status_code=201)
def add_child(report_id: uuid.UUID, package_id: uuid.UUID, body: ChildCreateIn,
              user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
              connection=Depends(get_connection)):
    child_id = service.add_child(connection, actor_id=user.user_id, request_id=_request_id(),
                                 report_id=report_id, package_id=package_id,
                                 child_bobbin_id=body.child_bobbin_id, package_slot=body.package_slot)
    return {"id": child_id}

@router.delete("/drafts/{report_id}/packages/{package_id}")
def remove_package(report_id: uuid.UUID, package_id: uuid.UUID, body: LogicalRemoveIn,
                   user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                   connection=Depends(get_connection)):
    service.remove_package(connection, actor_id=user.user_id, request_id=_request_id(),
                           report_id=report_id, package_id=package_id, reason=body.reason)
    return {"id": package_id, "removed": True}

@router.delete("/drafts/{report_id}/children/{child_id}")
def remove_child(report_id: uuid.UUID, child_id: uuid.UUID, body: LogicalRemoveIn,
                 user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                 connection=Depends(get_connection)):
    service.remove_child(connection, actor_id=user.user_id, request_id=_request_id(),
                         report_id=report_id, child_id=child_id, reason=body.reason)
    return {"id": child_id, "removed": True}

@router.post("/drafts/{report_id}/discard")
def discard_draft(report_id: uuid.UUID, body: LogicalRemoveIn,
                  user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                  connection=Depends(get_connection)):
    with connection.transaction():
        service._context(connection, user.user_id, _request_id(), body.reason)
        service._get_draft(connection, report_id, user.user_id, lock=True)
        connection.execute(
            """UPDATE vinto_txn.rewinding_export_report
               SET status='discarded',discarded_by=%s,discarded_at=clock_timestamp(),
                   discarded_reason=%s,updated_by=%s WHERE id=%s""",
            (user.user_id, body.reason, user.user_id, report_id),
        )
        service._event(connection, report_id, user.user_id, "draft_discarded", body.reason)
    return {"id": report_id, "status": "discarded"}

@router.get("/reports/{report_id}")
def get_report(report_id: uuid.UUID, response: Response,
               user: AuthenticatedUser = Depends(current_user),
               connection=Depends(get_connection)):
    response.headers["Cache-Control"] = "private, no-store"
    if not (user.can(REWINDING_EXPORT_READ_OWN) or user.can(REWINDING_EXPORT_READ_SECTOR)):
        raise HTTPException(status_code=403, detail="Permiso insuficiente")
    return service.get_report(connection, report_id=report_id, actor_id=user.user_id,
                              sectors=user.sectors, sector_wide=_sector_wide(user))

@router.get("/history", response_model=list[HistoryItemOut])
def history(response: Response, limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0),
            user: AuthenticatedUser = Depends(current_user),
            connection=Depends(get_connection)):
    if not (user.can(REWINDING_EXPORT_READ_OWN) or user.can(REWINDING_EXPORT_READ_SECTOR)):
        raise HTTPException(status_code=403, detail="Permiso insuficiente")
    response.headers["Cache-Control"] = "private, no-store"
    return service.list_history(connection, actor_id=user.user_id, sectors=user.sectors,
                                sector_wide=_sector_wide(user), limit=limit, offset=offset)

@router.get("/reports/{report_id}/pdf")
def download_pdf(report_id: uuid.UUID,
                 user: AuthenticatedUser = Depends(current_user),
                 connection=Depends(get_connection)):
    if not (user.can(REWINDING_EXPORT_READ_OWN) or user.can(REWINDING_EXPORT_READ_SECTOR)):
        raise HTTPException(status_code=403, detail="Permiso insuficiente")
    file_name, content, sha256, page_count = service.download_original_pdf(
        connection, report_id=report_id, actor_id=user.user_id, sectors=user.sectors,
        sector_wide=_sector_wide(user))
    return RawResponse(content=content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="{file_name}"',
        "Cache-Control": "private, no-store", "ETag": f'"{sha256}"',
        "X-RBE-PDF-Pages": str(page_count),
    })

@router.post("/reports/{report_id}/annul", response_model=AnnulOut)
def annul(report_id: uuid.UUID, body: AnnulIn,
          user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_ANNUL)),
          connection=Depends(get_connection)):
    return service.annul_report(connection, actor_id=user.user_id, request_id=_request_id(),
                                 report_id=report_id, reason=body.reason, sectors=user.sectors)

@router.get("/work-orders", response_model=list[ClassifiableWorkOrderOut])
def classifiable_work_orders(user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CLASSIFY_SOURCE)),
                             connection=Depends(get_connection)):
    return service.list_classifiable_work_orders(connection, sectors=user.sectors)

@router.post("/work-orders/{work_order_id}/classification", response_model=ClassificationOut, status_code=201)
def classify_work_order(work_order_id: uuid.UUID, body: ClassificationIn,
                        user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CLASSIFY_SOURCE)),
                        connection=Depends(get_connection)):
    classification_id = service.classify_work_order(
        connection, actor_id=user.user_id, request_id=_request_id(), work_order_id=work_order_id,
        classification=body.classification, reason=body.reason, sectors=user.sectors)
    return {"id": classification_id}


@router.get("/work-orders/{work_order_id}/classification")
def get_work_order_classification(work_order_id: uuid.UUID,
                                  user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CLASSIFY_SOURCE)),
                                  connection=Depends(get_connection)):
    return service.get_work_order_classification(connection, work_order_id=work_order_id, sectors=user.sectors)
