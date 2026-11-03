"""API de órdenes de trabajo BASE (Bobinas). Lectura: work_order.read. Crear, añadir línea y publicar: work_order.manage."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.assignments import service as assignments_service
from app.assignments.schemas import ActivateAllIn, ActivateAllOut, activate_all_out
from app.auth.dependencies import require_permission
from app.auth.permissions import ASSIGNMENT_MANAGE, WORK_ORDER_MANAGE, WORK_ORDER_READ
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.work_orders import service
from app.work_orders.schemas import CreateWorkOrderIn, LineIn, WorkOrderOut, work_order_out

router = APIRouter(prefix="/api/work-orders", tags=["Órdenes de trabajo"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente"},
    404: {"description": "Orden, máquina o artículo no encontrado (una OT fuera del alcance del actor es indistinguible de una inexistente)"},
    409: {"description": "Conflicto de estado (la línea base ya está publicada o no es publicable)"},
    422: {"description": "Datos inválidos, o línea en otra máquina con la compuerta MULTI_MACHINE_DISABLED apagada"},
}


def _manages(user: AuthenticatedUser) -> bool:
    """Una OT con líneas en varias máquinas solo la leen quienes la gestionan (Jefatura) o la activan (Supervisión), hasta que PR5 filtre por máquina."""
    return user.can(WORK_ORDER_MANAGE) or user.can(ASSIGNMENT_MANAGE)


def _request_id() -> str:
    return str(uuid.uuid4())  # nunca se confía en X-Request-ID del cliente


@router.post("", status_code=201, response_model=WorkOrderOut, responses=_ERRORS)
def create_work_order(body: CreateWorkOrderIn, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                      connection=Depends(get_connection)):
    view = service.create_work_order(connection, actor_id=user.user_id, machine_code=body.machine_code,
                                     lines=[line.to_domain() for line in body.lines], request_id=_request_id(), sectors=user.sectors)
    return work_order_out(view)


@router.get("", response_model=list[WorkOrderOut], responses=_ERRORS)
def list_work_orders(machine_code: str | None = Query(default=None, max_length=64),
                     status: Literal["draft", "published", "in_progress", "closed"] | None = None,
                     limit: int = Query(default=service.DEFAULT_LIST_LIMIT, ge=1, le=service.MAX_LIST_LIMIT),
                     user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_READ)), connection=Depends(get_connection)):
    return [work_order_out(v) for v in service.list_work_orders(connection, machine_code=machine_code, status=status, limit=limit, sectors=user.sectors,
                                                                       multi_machine_visible=_manages(user))]


@router.get("/{work_order_id}", response_model=WorkOrderOut, responses=_ERRORS)
def get_work_order(work_order_id: str, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_READ)),
                   connection=Depends(get_connection)):
    return work_order_out(service.get_work_order(connection, work_order_id, sectors=user.sectors, multi_machine_visible=_manages(user)))


@router.post("/{work_order_id}/lines", status_code=201, response_model=WorkOrderOut, responses=_ERRORS)
def add_line(work_order_id: str, body: LineIn, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
             connection=Depends(get_connection)):
    return work_order_out(service.add_line(connection, actor_id=user.user_id, work_order_id=work_order_id,
                                           line=body.to_domain(), request_id=_request_id(), sectors=user.sectors))


@router.post("/{work_order_id}/publish", response_model=WorkOrderOut, responses=_ERRORS)
def publish_work_order(work_order_id: str, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                       connection=Depends(get_connection)):
    return work_order_out(service.publish_work_order(connection, actor_id=user.user_id, work_order_id=work_order_id,
                                                     request_id=_request_id(), sectors=user.sectors))


@router.post("/{work_order_id}/activate-all", response_model=ActivateAllOut,
             responses={200: {"description": "Vista previa, o confirmación sin cambios (ya vigente)"}, 201: {"description": "Líneas activadas"}, **_ERRORS})
def activate_all(work_order_id: str, body: ActivateAllIn, response: Response, user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE)),
                 connection=Depends(get_connection)):
    """Activación masiva en dos fases (solo Supervisión, `assignment.manage`; requiere la compuerta multimáquina del servidor).

    `{"dry_run": true}`: vista previa de solo lectura con `plan_hash`. `{"dry_run": false, "plan_hash": "..."}`: confirma TODO O NADA.
    409: el estado cambió desde la vista previa (ACTIVATION_PLAN_CHANGED) o hay bloqueos/conflictos (ACTIVATION_BLOCKED, otra OT en la máquina, etc.).
    El 404 también cubre una OT con alguna máquina fuera del alcance del actor. 422: compuerta apagada (MULTI_MACHINE_DISABLED) o cuerpo inválido.
    """
    if body.dry_run:
        return activate_all_out(assignments_service.preview_activate_all(connection, work_order_id=work_order_id, sectors=user.sectors))
    result = assignments_service.activate_all(connection, actor_id=user.user_id, work_order_id=work_order_id, plan_hash=body.plan_hash,
                                              request_id=_request_id(), sectors=user.sectors)
    response.status_code = 201 if result.outcome == "applied" else 200
    return activate_all_out(result, plan_hash=body.plan_hash)
