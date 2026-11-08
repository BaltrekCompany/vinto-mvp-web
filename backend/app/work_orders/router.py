"""API de órdenes de trabajo BASE (Bobinas). Lectura: work_order.read. Crear, añadir línea y publicar: work_order.manage."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.assignments import service as assignments_service
from app.assignments.schemas import ActivateAllIn, ActivateAllOut, activate_all_out
from app.auth.dependencies import FORBIDDEN, require_permission
from app.auth.permissions import ASSIGNMENT_MANAGE, WORK_ORDER_MANAGE, WORK_ORDER_READ
from app.auth.service import AuthenticatedUser
from app.authz import visibility
from app.config import settings
from app.database import get_connection
from app.work_orders import service
from app.work_orders import line_execution
from app.work_orders import reprogramming
from app.work_orders import close_order
from app.work_orders.schemas import CreateWorkOrderIn, EditDraftLineIn, LineIn, ReprogramPublishedLineIn, RevisionOut, WorkOrderOut, work_order_out

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


class CapabilitiesOut(BaseModel):
    """Lo ÚNICO que se publica: si el servidor acepta OT con líneas en varias máquinas. Sin otros ajustes, versiones ni datos de OT."""

    multi_machine: bool


def capabilities_reader(user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_READ))) -> AuthenticatedUser:
    """Mínimo apropiado: quien GESTIONA OT (Jefatura) o las activa (Supervisión). Operación, Calidad y DATA_BALTREK no necesitan esta consulta: 403."""
    if not _manages(user):
        raise HTTPException(status_code=403, detail=FORBIDDEN)
    return user


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
                     archived: bool = False,
                     limit: int = Query(default=service.DEFAULT_LIST_LIMIT, ge=1, le=service.MAX_LIST_LIMIT),
                     user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_READ)), connection=Depends(get_connection)):
    # Archived history is explicitly opt-in for managerial profiles only.
    if archived and not _manages(user):
        raise HTTPException(status_code=403, detail=FORBIDDEN)
    scope = visibility.legacy_scope(connection, user, "work_orders.list")
    return [work_order_out(v) for v in service.list_work_orders(connection, machine_code=machine_code, status=status, limit=limit, sectors=user.sectors,
                                                                       multi_machine_visible=_manages(user) or scope is not None, machine_codes=scope,
                                                                       archived=archived)]


# DEBE ir antes de `/{work_order_id}`: de lo contrario «capabilities» se interpretaría como el identificador de una OT.
@router.get("/capabilities", response_model=CapabilitiesOut, responses={401: _ERRORS[401], 403: _ERRORS[403]})
def capabilities(response: Response, user: AuthenticatedUser = Depends(capabilities_reader)):
    """Capacidades de OT que el SERVIDOR confirma a la sesión (solo lectura). `multi_machine` refleja la compuerta de servidor WORK_ORDERS_MULTI_MACHINE_ENABLED
    (apagada por defecto); el cliente no puede cambiarla con query, cabeceras ni cuerpo, y no es una autorización: el POST de creación vuelve a validarlo todo."""
    response.headers["Cache-Control"] = "private, no-store"
    return CapabilitiesOut(multi_machine=settings.work_orders_multi_machine_enabled is True)


class ExecutionCapabilitiesOut(BaseModel):
    line_execution: bool


# Independent of the historical /capabilities schema, which must continue to
# return exactly {"multi_machine": bool} for existing deployed clients.
@router.get("/execution-capabilities", response_model=ExecutionCapabilitiesOut,
            responses={401: _ERRORS[401], 403: _ERRORS[403]})
def execution_capabilities(
        response: Response,
        user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE))):
    response.headers["Cache-Control"] = "private, no-store"
    return ExecutionCapabilitiesOut(line_execution=settings.work_order_line_execution_enabled is True)


@router.get("/{work_order_id}", response_model=WorkOrderOut, responses=_ERRORS)
def get_work_order(work_order_id: str, include_archived: bool = False,
                   user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_READ)),
                   connection=Depends(get_connection)):
    if include_archived and not _manages(user):
        raise HTTPException(status_code=403, detail=FORBIDDEN)
    scope = visibility.legacy_scope(connection, user, "work_orders.detail")
    return work_order_out(service.get_work_order(connection, work_order_id, sectors=user.sectors,
                          multi_machine_visible=_manages(user) or scope is not None,
                          machine_codes=scope, include_archived=include_archived))


class ArchiveWorkOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=300)


@router.post("/{work_order_id}/archive", response_model=WorkOrderOut, responses=_ERRORS)
def archive_work_order(work_order_id: str, body: ArchiveWorkOrderIn,
                       user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                       connection=Depends(get_connection)):
    """Jefatura only. Draft/published, no assignments. Never deletes history."""
    return work_order_out(service.archive_work_order(
        connection, actor_id=user.user_id, work_order_id=work_order_id,
        reason=body.reason, sectors=user.sectors, request_id=_request_id()))


@router.post("/{work_order_id}/restore", response_model=WorkOrderOut, responses=_ERRORS)
def restore_work_order(work_order_id: str,
                       user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                       connection=Depends(get_connection)):
    """Jefatura only. Restore visibility; original work-order status remains."""
    return work_order_out(service.restore_work_order(
        connection, actor_id=user.user_id, work_order_id=work_order_id,
        sectors=user.sectors, request_id=_request_id()))


@router.post("/{work_order_id}/lines", status_code=201, response_model=WorkOrderOut, responses=_ERRORS)
def add_line(work_order_id: str, body: LineIn, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
             connection=Depends(get_connection)):
    return work_order_out(service.add_line(connection, actor_id=user.user_id, work_order_id=work_order_id,
                                           line=body.to_domain(), request_id=_request_id(), sectors=user.sectors))


@router.post("/{work_order_id}/lines/{line_code}/edit-draft", response_model=WorkOrderOut, responses=_ERRORS)
def edit_draft_line(work_order_id: str, line_code: str, body: EditDraftLineIn,
                    user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                    connection=Depends(get_connection)):
    """Edición exclusiva de borradores, sin cambiar máquina ni identidad.

    La operación nunca acepta OT publicadas o en producción. La autorización
    efectiva, el bloqueo y la comprobación de la versión leída son del servidor.
    """
    return work_order_out(service.edit_draft_line(
        connection, actor_id=user.user_id, work_order_id=work_order_id,
        line_code=line_code, expected=body.expected.to_domain(),
        replacement=body.replacement.to_domain(), reason=body.reason,
        request_id=_request_id(), sectors=user.sectors))


@router.post("/{work_order_id}/lines/{line_code}/reprogram", response_model=WorkOrderOut, responses=_ERRORS)
def reprogram_published_line(work_order_id: str, line_code: str, body: ReprogramPublishedLineIn,
                             user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                             connection=Depends(get_connection)):
    """E2-B: only a published OT WITHOUT ANY assignment/execution history."""
    return work_order_out(reprogramming.reprogram_published_line(
        connection, actor_id=user.user_id, work_order_id=work_order_id,
        line_code=line_code, expected_version=body.expected_version,
        expected=body.expected.to_domain(), replacement=body.replacement.to_domain(),
        reason=body.reason, request_id=_request_id(), sectors=user.sectors))


@router.get("/{work_order_id}/revisions", response_model=list[RevisionOut], responses=_ERRORS)
def list_revisions(work_order_id: str,
                   user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                   connection=Depends(get_connection)):
    """Jefatura-only immutable version history: before/after, reason, actor, timestamp."""
    return reprogramming.revision_history(
        connection, work_order_id=work_order_id, sectors=user.sectors)


@router.post("/{work_order_id}/publish", response_model=WorkOrderOut, responses=_ERRORS)
def publish_work_order(work_order_id: str, user: AuthenticatedUser = Depends(require_permission(WORK_ORDER_MANAGE)),
                       connection=Depends(get_connection)):
    return work_order_out(service.publish_work_order(connection, actor_id=user.user_id, work_order_id=work_order_id,
                                                     request_id=_request_id(), sectors=user.sectors))


@router.post("/{work_order_id}/close", response_model=WorkOrderOut, responses=_ERRORS)
def close_work_order(work_order_id: str,
                     user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE)),
                     connection=Depends(get_connection)):
    """E1-07: Supervisión alone closes the OT; all baseline lines must be finished.

    Never imply cancellation from a planned-versus-actual deficit. Closing a
    logical line does NOT close the OT; this is a separate, explicit action.
    """
    try:
        return work_order_out(close_order.close_work_order(
            connection, actor_id=user.user_id, work_order_id=work_order_id,
            sectors=user.sectors, request_id=_request_id()))
    except close_order.WorkOrderCloseBlockedError as error:
        # Pending codes belong only to baseline lines already checked in the
        # actor's full OT scope, never to another sector's private lines.
        return JSONResponse(status_code=409, content={
            "detail": error.public_message, "code": error.code,
            "pending_lines": list(error.pending_lines),
        })


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


class LineExecutionStateOut(BaseModel):
    baseline_line_id: uuid.UUID
    line_code: str
    machine_code: str
    status: Literal["planned", "enabled", "in_production", "finished", "requires_review"]
    current_assignment_id: uuid.UUID | None
    started_at: datetime | None
    started_by: uuid.UUID | None
    finished_at: datetime | None
    finished_by: uuid.UUID | None


class WorkOrderExecutionOut(BaseModel):
    work_order_id: uuid.UUID
    lines: list[LineExecutionStateOut]


@router.get("/{work_order_id}/execution", response_model=WorkOrderExecutionOut,
            responses={401: _ERRORS[401], 403: _ERRORS[403], 404: _ERRORS[404], 422: _ERRORS[422]})
def get_work_order_execution(work_order_id: str, response: Response,
                             user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE)),
                             connection=Depends(get_connection)):
    """Supervisor-only read; never uses assignment.active as proxy for production."""
    response.headers["Cache-Control"] = "private, no-store"
    return line_execution.read_work_order_execution(
        connection, work_order_id=work_order_id, sectors=user.sectors)


class StartLineIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignment_id: uuid.UUID  # Current assignment of the explicitly selected line


class LineExecutionOut(BaseModel):
    baseline_line_id: uuid.UUID
    work_order_id: uuid.UUID
    line_code: str
    machine_code: str
    status: Literal["planned", "enabled", "in_production", "finished"]
    started_at: datetime | None
    started_by: uuid.UUID | None
    finished_at: datetime | None
    finished_by: uuid.UUID | None


@router.post("/{work_order_id}/lines/{line_code}/start", response_model=LineExecutionOut, responses=_ERRORS)
def start_line(work_order_id: str, line_code: str, body: StartLineIn,
               user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE)),
               connection=Depends(get_connection)):
    """E1-03 Supervisión only; a shift assignment is not a logical line execution."""
    return line_execution.start_line(
        connection, actor_id=user.user_id, work_order_id=work_order_id,
        line_code=line_code, assignment_id=body.assignment_id,
        sectors=user.sectors, request_id=_request_id())


@router.post("/{work_order_id}/lines/{line_code}/finish", response_model=LineExecutionOut, responses=_ERRORS)
def finish_line(work_order_id: str, line_code: str,
                user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE)),
                connection=Depends(get_connection)):
    """E1-03: finish the logical line, never the entire OT."""
    return line_execution.finish_line(
        connection, actor_id=user.user_id, work_order_id=work_order_id,
        line_code=line_code, sectors=user.sectors, request_id=_request_id())
