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
from app.rewinding_export import service, repository, lifecycle
from app.rewinding_export.schemas import (
    AnnulIn, AnnulOut, ChildCreateIn, ChildCreatedOut, ClassificationIn, ClassificationOut,
    ClassifiableWorkOrderOut, DraftCreateIn, DraftCreatedOut, DraftHeaderIn, HistoryItemOut,
    LogicalRemoveIn, PackageCreateIn, PackageWithChildrenIn, PackageCreatedOut,
)
router = APIRouter(prefix="/api/reports/rewinding-export", tags=["Bobinas refiladas para exportación"])

def _request_id():
    return str(uuid.uuid4())

def _sector_wide(user: AuthenticatedUser) -> bool:
    return user.can(REWINDING_EXPORT_READ_SECTOR)


@router.get("/mothers")
def eligible_mothers(response: Response,
                    pv_reference: str | None = Query(default=None, max_length=100),
                    article_id: uuid.UUID | None = Query(default=None),
                    article_code: str | None = Query(default=None, max_length=64),
                    user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                    connection=Depends(get_connection)):
    response.headers["Cache-Control"] = "private, no-store"
    repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=False)
    rows = repository.visible_mother_rows(connection, user, pv_reference=pv_reference, article_id=article_id)
    return {"items": [option for row in rows
                      if (article_code is None or row["article_code"] == article_code)
                      for option in [repository.mother_row_to_option(row)] if option is not None]}

@router.post("/drafts", status_code=201)
def create_draft(body: DraftCreateIn, user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                 connection=Depends(get_connection)):
    with connection.transaction():
        repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=True)
        article = repository.one(connection,
            "SELECT code FROM vinto_master.article WHERE id=%s AND active AND is_product",
            (body.article_id,))
        if article is None:
            raise HTTPException(status_code=404, detail="Producto no encontrado")
        report_id = service.create_draft(connection, actor_id=user.user_id, request_id=_request_id(),
                                         pv_reference=body.pv_reference, article_code=article["code"], sectors=user.sectors)
        service.update_draft(connection, actor_id=user.user_id, request_id=_request_id(), report_id=report_id,
                             truck_number=body.truck_number, order_number=body.order_number,
                             observations=body.observations)
        return repository.load_draft(connection, user.user_id, report_id)

@router.patch("/drafts/{report_id}")
def update_draft(report_id: uuid.UUID, body: DraftHeaderIn,
                 user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                 connection=Depends(get_connection)):
    with connection.transaction():
        repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=True)
        service.update_draft(connection, actor_id=user.user_id, request_id=_request_id(), report_id=report_id,
                             truck_number=body.truck_number, order_number=body.order_number,
                             observations=body.observations)
        return repository.load_draft(connection, user.user_id, report_id)

@router.post("/drafts/{report_id}/packages", status_code=201)
def add_package(report_id: uuid.UUID, body: PackageWithChildrenIn,
                user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                connection=Depends(get_connection)):
    if len({child.package_slot for child in body.children}) != len(body.children) or not any(
        child.package_slot == "A" for child in body.children
    ) or len({child.child_bobbin_id for child in body.children}) != len(body.children):
        raise HTTPException(status_code=422, detail="Paquete requiere cría A y selecciones únicas")
    with connection.transaction():
        source = service._source_mother(connection, body.mother_capture_id)
        from app.authz import require, Operation
        require(connection, user, Operation.REWINDING_EXPORT_CREATE, source["machine_code"], "VINTO-P1-07", lock=True)
        package_id = service.add_package(connection, actor_id=user.user_id, request_id=_request_id(),
                                         report_id=report_id, mother_capture_id=body.mother_capture_id, sectors=user.sectors)
        for child in body.children:
            service.add_child(connection, actor_id=user.user_id, request_id=_request_id(),
                              report_id=report_id, package_id=package_id, child_bobbin_id=child.child_bobbin_id,
                              package_slot=child.package_slot)
        return repository.load_draft(connection, user.user_id, report_id)


@router.patch("/drafts/{report_id}/packages/{package_id}")
def update_package(report_id: uuid.UUID, package_id: uuid.UUID, body: PackageWithChildrenIn,
                   user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                   connection=Depends(get_connection)):
    if len({child.package_slot for child in body.children}) != len(body.children) or not any(
        child.package_slot == "A" for child in body.children
    ) or len({child.child_bobbin_id for child in body.children}) != len(body.children):
        raise HTTPException(status_code=422, detail="Paquete requiere cría A y selecciones únicas")
    with connection.transaction():
        source = service._source_mother(connection, body.mother_capture_id)
        from app.authz import require, Operation
        require(connection, user, Operation.REWINDING_EXPORT_CREATE, source["machine_code"], "VINTO-P1-07", lock=True)
        service._context(connection, user.user_id, _request_id(), "RBE package children updated")
        service._get_draft(connection, report_id, user.user_id, lock=True)
        package = repository.one(connection,
            "SELECT mother_capture_id FROM vinto_txn.rewinding_export_package WHERE id=%s AND report_id=%s AND removed_at IS NULL FOR UPDATE",
            (package_id, report_id))
        if not package or package["mother_capture_id"] != body.mother_capture_id:
            raise HTTPException(status_code=409, detail="La madre no puede cambiarse en un paquete existente")
        connection.execute("""UPDATE vinto_txn.rewinding_export_package_child
            SET removed_at=clock_timestamp(), removed_by=%s, updated_by=%s
            WHERE report_id=%s AND package_id=%s AND removed_at IS NULL""",
            (user.user_id, user.user_id, report_id, package_id))
        for child in body.children:
            service.add_child(connection, actor_id=user.user_id, request_id=_request_id(),
                              report_id=report_id, package_id=package_id, child_bobbin_id=child.child_bobbin_id,
                              package_slot=child.package_slot)
        return repository.load_draft(connection, user.user_id, report_id)


@router.post("/drafts/{report_id}/packages/{package_id}/remove")
def remove_package_for_ui(report_id: uuid.UUID, package_id: uuid.UUID,
                          user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                          connection=Depends(get_connection)):
    with connection.transaction():
        repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=True)
        service.remove_package(connection, actor_id=user.user_id, request_id=_request_id(),
                               report_id=report_id, package_id=package_id, reason="RBE draft package removed")
        return repository.load_draft(connection, user.user_id, report_id)


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
def discard_draft(report_id: uuid.UUID, body: LogicalRemoveIn | None = None,
                  user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                  connection=Depends(get_connection)):
    with connection.transaction():
        service._context(connection, user.user_id, _request_id(), body.reason if body else "RBE draft discarded")
        repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=True)
        service._get_draft(connection, report_id, user.user_id, lock=True)
        connection.execute(
            """UPDATE vinto_txn.rewinding_export_report
               SET status='discarded',discarded_by=%s,discarded_at=clock_timestamp(),
                   discarded_reason=%s,updated_by=%s WHERE id=%s""",
            (user.user_id, body.reason if body else "RBE draft discarded", user.user_id, report_id),
        )
        service._event(connection, report_id, user.user_id, "draft_discarded", body.reason if body else "RBE draft discarded")
    return {"discarded": True}

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
    return service.annul_report(connection, user=user, actor_id=user.user_id, request_id=_request_id(),
                                 report_id=report_id, reason=body.reason, sectors=user.sectors)

@router.get("/work-orders")
def classifiable_work_orders(user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CLASSIFY_SOURCE)),
                             connection=Depends(get_connection)):
    return {"items": lifecycle.list_work_orders_for_classification(connection, user)}

@router.post("/work-orders/{work_order_id}/classification", status_code=201)
def classify_work_order(work_order_id: uuid.UUID, body: ClassificationIn,
                        user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CLASSIFY_SOURCE)),
                        connection=Depends(get_connection)):
    return lifecycle.classify_work_order(connection, user, work_order_id, body, request_id=_request_id())

@router.get("/work-orders/{work_order_id}/classification")
def get_work_order_classification(work_order_id: uuid.UUID,
                                  user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CLASSIFY_SOURCE)),
                                  connection=Depends(get_connection)):
    return lifecycle.get_work_order_classification(connection, user, work_order_id)

# RBE-03: read contracts are response-compatible, and each request checks live grants.
@router.get("/pvs")
def list_pvs(response: Response, user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
             connection=Depends(get_connection)):
    response.headers["Cache-Control"] = "private, no-store"
    repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=False)
    mothers = repository.visible_mother_rows(connection, user)
    counts = {}
    for mother in mothers:
        pv = mother["pv_reference"]
        counts[pv] = counts.get(pv, 0) + 1
    return {"items": [{"pv_reference": pv, "eligible_mothers": count} for pv, count in sorted(counts.items())]}


@router.get("/products")
def list_products(pv_reference: str = Query(min_length=1, max_length=100),
                  response: Response = None,
                  user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                  connection=Depends(get_connection)):
    repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=False)
    mothers = repository.visible_mother_rows(connection, user, pv_reference=pv_reference)
    products = {}
    for row in mothers:
        item = products.get(row["article_id"])
        if item is None:
            products[row["article_id"]] = {"article_id": row["article_id"], "code": row["article_code"],
                                           "description": row["article_description"]}
        elif item["description"] != row["article_description"]:
            item["description"] = ""
    return {"items": sorted(products.values(), key=lambda item: (item["code"], str(item["article_id"])))}


@router.get("/mothers/{mother_capture_id}/children")
def list_children(mother_capture_id: uuid.UUID,
                  user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                  connection=Depends(get_connection)):
    repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=False)
    candidates = repository.visible_mother_rows(connection, user)
    if not any(row["mother_capture_id"] == mother_capture_id for row in candidates):
        raise HTTPException(status_code=404, detail="Madre no elegible")
    return {"items": repository.rows(connection, """
        SELECT b.id AS bobbin_id, b.source_capture_id AS mother_capture_id,
               b.rewind_child_position AS position, b.weight_kg::text AS weight_kg,
               'released'::text AS quality_status
        FROM vinto_txn.bobbin b
        JOIN vinto_txn.quality_release q ON q.bobbin_id=b.id AND q.status='released'
        WHERE b.source_capture_id=%s AND b.rewind_child_position BETWEEN 1 AND 22
          AND b.rewind_child_position<>12 AND b.weight_kg>0
          AND NOT EXISTS (SELECT 1 FROM vinto_txn.rewinding_export_reservation res
                          WHERE res.child_bobbin_id=b.id AND res.released_at IS NULL)
        ORDER BY b.rewind_child_position,b.id
    """, (mother_capture_id,))}


@router.get("/drafts")
def list_drafts(user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_READ_OWN)),
                connection=Depends(get_connection)):
    repository.require_sector_permission(connection, user, REWINDING_EXPORT_READ_OWN, lock=False)
    return {"items": repository.rows(connection, """
        SELECT r.id, r.created_at, r.pv_reference, r.article_code_snapshot AS article_code,
               m.code AS machine_code,
               (SELECT count(*) FROM vinto_txn.rewinding_export_package p
                WHERE p.report_id=r.id AND p.removed_at IS NULL)::integer AS package_count
        FROM vinto_txn.rewinding_export_report r
        LEFT JOIN vinto_master.machine m ON m.id=r.machine_id
        WHERE r.created_by=%s AND r.status='draft' AND r.sector_id=(
          SELECT id FROM vinto_master.sector WHERE code='REBOBINADO')
        ORDER BY r.created_at DESC,r.id
    """, (user.user_id,))}


@router.get("/drafts/{report_id}")
def load_draft(report_id: uuid.UUID,
               user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_READ_OWN)),
               connection=Depends(get_connection)):
    repository.require_sector_permission(connection, user, REWINDING_EXPORT_READ_OWN, lock=False)
    return repository.load_draft(connection, user.user_id, report_id)


@router.post("/drafts/{report_id}/preview")
def preview_draft(report_id: uuid.UUID,
                  user: AuthenticatedUser = Depends(require_permission(REWINDING_EXPORT_CREATE)),
                  connection=Depends(get_connection)):
    repository.require_sector_permission(connection, user, REWINDING_EXPORT_CREATE, lock=False)
    draft = repository.load_draft(connection, user.user_id, report_id)
    errors = []
    packages = draft["packages"]
    if not packages:
        errors.append({"code": "V01", "message": "Se requiere al menos un paquete."})
    if not draft["truck_number"].strip() or not draft["order_number"].strip():
        errors.append({"code": "V02", "message": "Camión y orden son obligatorios."})
    total = sum(len(p["children"]) for p in packages)
    used = set()
    for package in packages:
        children = package["children"]
        slots = {child["package_slot"] for child in children}
        if not 1 <= len(children) <= 5 or "A" not in slots:
            errors.append({"code": "V03", "message": "Cada paquete requiere de una a cinco crías e incluir A."})
        for child in children:
            if child["bobbin_id"] in used:
                errors.append({"code": "V04", "message": "Una cría se repite en el borrador."})
            used.add(child["bobbin_id"])
    # This is a draft preview; generation re-checks live grants, quality and reservations.
    return {"valid": not errors, "package_count": len(packages), "child_count": total,
            "warnings": [], "blocking_errors": errors}
