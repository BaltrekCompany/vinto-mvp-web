"""API de órdenes de trabajo BASE (Bobinas). Lectura: work_order.read. Crear, añadir línea y publicar: work_order.manage."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query

from app.auth.dependencies import require_permission
from app.auth.permissions import WORK_ORDER_MANAGE, WORK_ORDER_READ
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.work_orders import service
from app.work_orders.schemas import CreateWorkOrderIn, LineIn, WorkOrderOut, work_order_out

router = APIRouter(prefix="/api/work-orders", tags=["Órdenes de trabajo"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente"},
    404: {"description": "Orden, máquina o artículo no encontrado"},
    409: {"description": "Conflicto de estado (la línea base ya está publicada o no es publicable)"},
    422: {"description": "Datos inválidos"},
}


def _request_id() -> str:
    return str(uuid.uuid4())  # nunca se confía en X-Request-ID del cliente


@router.post("", status_code=201, response_model=WorkOrderOut, responses=_ERRORS)
def create_work_order(body: CreateWorkOrderIn, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                      connection=Depends(get_connection)):
    view = service.create_work_order(connection, actor_id=user.user_id, machine_code=body.machine_code,
                                     lines=[line.to_domain() for line in body.lines], request_id=_request_id())
    return work_order_out(view)


@router.get("", response_model=list[WorkOrderOut], responses=_ERRORS)
def list_work_orders(machine_code: str | None = Query(default=None, max_length=64),
                     status: Literal["draft", "published", "in_progress", "closed"] | None = None,
                     limit: int = Query(default=service.DEFAULT_LIST_LIMIT, ge=1, le=service.MAX_LIST_LIMIT),
                     _user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_READ)), connection=Depends(get_connection)):
    return [work_order_out(v) for v in service.list_work_orders(connection, machine_code=machine_code, status=status, limit=limit)]


@router.get("/{work_order_id}", response_model=WorkOrderOut, responses=_ERRORS)
def get_work_order(work_order_id: str, _user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_READ)),
                   connection=Depends(get_connection)):
    return work_order_out(service.get_work_order(connection, work_order_id))


@router.post("/{work_order_id}/lines", status_code=201, response_model=WorkOrderOut, responses=_ERRORS)
def add_line(work_order_id: str, body: LineIn, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
             connection=Depends(get_connection)):
    return work_order_out(service.add_line(connection, actor_id=user.user_id, work_order_id=work_order_id,
                                           line=body.to_domain(), request_id=_request_id()))


@router.post("/{work_order_id}/publish", response_model=WorkOrderOut, responses=_ERRORS)
def publish_work_order(work_order_id: str, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                       connection=Depends(get_connection)):
    return work_order_out(service.publish_work_order(connection, actor_id=user.user_id, work_order_id=work_order_id,
                                                     request_id=_request_id()))
