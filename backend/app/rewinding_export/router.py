from __future__ import annotations
from uuid import UUID
from fastapi import APIRouter, Depends, Request
from app.auth.dependencies import current_user
from app.database import get_connection
from . import lifecycle, service
from .schemas import AnnulInput, ClassificationInput, CreateDraftInput, DraftOut, PackageInput, PreviewOut, UpdateDraftInput

router = APIRouter(prefix="/api/reports/rewinding-export", tags=["rewinding-export"])

def _request_id(request: Request) -> str | None:
    return request.headers.get("X-Request-ID")

@router.get("/pvs")
def get_pvs(connection=Depends(get_connection), user=Depends(current_user)):
    return {"items": service.list_pvs(connection,user)}

@router.get("/products")
def get_products(pv_reference: str, connection=Depends(get_connection), user=Depends(current_user)):
    return {"items": service.list_products(connection,user,pv_reference)}

@router.get("/mothers")
def get_mothers(pv_reference: str, article_id: UUID, connection=Depends(get_connection), user=Depends(current_user)):
    return {"items": service.list_mothers(connection,user,pv_reference,article_id)}

@router.get("/mothers/{mother_capture_id}/children")
def get_children(mother_capture_id: UUID, connection=Depends(get_connection), user=Depends(current_user)):
    return {"items": service.list_children(connection,user,mother_capture_id)}

@router.get("/drafts")
def get_drafts(connection=Depends(get_connection), user=Depends(current_user)):
    return {"items": service.list_drafts(connection,user)}

@router.post("/drafts",response_model=DraftOut,status_code=201)
def post_draft(payload:CreateDraftInput,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return service.create_draft(connection,user,payload,request_id=_request_id(request))

@router.get("/drafts/{report_id}",response_model=DraftOut)
def get_draft(report_id:UUID,connection=Depends(get_connection),user=Depends(current_user)):
    return service.get_draft(connection,user,report_id)

@router.patch("/drafts/{report_id}",response_model=DraftOut)
def patch_draft(report_id:UUID,payload:UpdateDraftInput,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return service.update_draft_header(connection,user,report_id,payload,request_id=_request_id(request))

@router.post("/drafts/{report_id}/packages",response_model=DraftOut,status_code=201)
def post_package(report_id:UUID,payload:PackageInput,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return service.add_package(connection,user,report_id,payload,request_id=_request_id(request))

@router.patch("/drafts/{report_id}/packages/{package_id}",response_model=DraftOut)
def patch_package(report_id:UUID,package_id:UUID,payload:PackageInput,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return service.update_package(connection,user,report_id,package_id,payload,request_id=_request_id(request))

@router.post("/drafts/{report_id}/packages/{package_id}/remove",response_model=DraftOut)
def post_remove_package(report_id:UUID,package_id:UUID,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return service.remove_package(connection,user,report_id,package_id,request_id=_request_id(request))

@router.post("/drafts/{report_id}/discard")
def post_discard(report_id:UUID,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return service.discard_draft(connection,user,report_id,request_id=_request_id(request))

@router.post("/drafts/{report_id}/preview",response_model=PreviewOut)
def post_preview(report_id:UUID,connection=Depends(get_connection),user=Depends(current_user)):
    return service.preview_draft(connection,user,report_id)

@router.post("/drafts/{report_id}/annul")
def post_annul(report_id:UUID,payload:AnnulInput,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return lifecycle.annul_report(connection,user,report_id,payload.reason,request_id=_request_id(request))

@router.get("/work-orders")
def get_work_orders(connection=Depends(get_connection),user=Depends(current_user)):
    return {"items":lifecycle.list_work_orders_for_classification(connection,user)}

@router.get("/work-orders/{work_order_id}/classification")
def get_classification(work_order_id:UUID,connection=Depends(get_connection),user=Depends(current_user)):
    return lifecycle.get_work_order_classification(connection,user,work_order_id)

@router.post("/work-orders/{work_order_id}/classification")
def post_classification(work_order_id:UUID,payload:ClassificationInput,request:Request,connection=Depends(get_connection),user=Depends(current_user)):
    return lifecycle.classify_work_order(connection,user,work_order_id,payload,request_id=_request_id(request))
