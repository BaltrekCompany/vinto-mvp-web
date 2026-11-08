"""API de asignaciones de Bobinas. Lectura: assignment.read. Activar y finalizar: assignment.manage (Supervisión)."""

import uuid
from datetime import date, datetime
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, ConfigDict, Field

from app.assignments import service
from app.assignments import execution_read
from app.assignments import revision_notices
from app.assignments.schemas import (ActivateIn, ActivationOut, ActiveLinesOut, ActiveOut, AssignmentOut, OperationalLinesOut,
                                     activation_out, active_lines_out, active_out, assignment_out, operational_lines_out)
from app.auth.dependencies import require_permission
from app.auth.permissions import ASSIGNMENT_MANAGE, ASSIGNMENT_READ, PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz import visibility
from app.database import get_connection

router = APIRouter(prefix="/api/assignments", tags=["Asignaciones"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente"},
    404: {"description": "OT, línea o asignación inexistente"},
    409: {"description": "Estado incompatible o turno no configurado"},
    422: {"description": "Entrada inválida"},
}


def _request_id() -> str:
    return str(uuid.uuid4())  # nunca se confía en X-Request-ID del cliente


@router.post("/activate", response_model=ActivationOut, responses={201: {"description": "Asignación creada"}, **_ERRORS})
def activate(body: ActivateIn, response: Response, user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE)),
             connection=Depends(get_connection)):
    """201 si se creó una asignación nueva; 200 si ya estaba activa para esa línea, turno y fecha (idempotente)."""
    result = service.activate(connection, actor_id=user.user_id, work_order_id=body.work_order_id,
                              baseline_line_id=body.baseline_line_id, request_id=_request_id(), sectors=user.sectors)
    response.status_code = 201 if result.created else 200
    return activation_out(result)


@router.post("/{assignment_id}/finish", response_model=AssignmentOut, responses=_ERRORS)
def finish(assignment_id: str, user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_MANAGE)), connection=Depends(get_connection)):
    return assignment_out(service.finish(connection, actor_id=user.user_id, assignment_id=assignment_id, request_id=_request_id(), sectors=user.sectors))


class AssignmentExecutionStateOut(BaseModel):
    assignment_id: UUID
    status: Literal["planned", "enabled", "in_production", "finished", "requires_review"]


class MachineExecutionOut(BaseModel):
    line_execution: bool
    assignments: list[AssignmentExecutionStateOut]


@router.get("/execution-status", response_model=MachineExecutionOut, responses=_ERRORS)
def machine_execution_status(
        response: Response,
        machine_code: str = Query(max_length=64),
        user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_READ)),
        connection=Depends(get_connection)):
    """E1-06: scoped read for Operación. Assignment.active is not proof of production."""
    response.headers["Cache-Control"] = "private, no-store"
    return execution_read.read_machine_execution(
        connection, machine_code=machine_code, sectors=user.sectors,
        machine_codes=visibility.operational_scope(connection, user))



class RevisionNoticeOut(BaseModel):
    assignment_id: UUID
    version_number: int
    work_order_number: str
    line_code: str
    machine_code: str
    reason: str
    revised_at: datetime
    acknowledged_at: datetime | None
    pv_reference: str
    article_code: str
    quantity: str
    due_date: date


class AcknowledgeRevisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)  # version 1 is valid input but conflicts with any revised assignment (409)


class RevisionReceiptOut(BaseModel):
    assignment_id: UUID
    version_number: int
    acknowledged_at: datetime


@router.get("/revision-notices", response_model=list[RevisionNoticeOut], responses=_ERRORS)
def list_revision_notices(
        response: Response,
        user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
        connection=Depends(get_connection)):
    """Operator inbox: only active assignments on machines currently granted by MF13."""
    response.headers["Cache-Control"] = "private, no-store"
    return revision_notices.list_revision_notices(
        connection, user_id=user.user_id, sectors=user.sectors,
        machine_codes=visibility.authorized_production_machine_codes(connection, user))


@router.post("/{assignment_id}/acknowledge-revision", response_model=RevisionReceiptOut, responses=_ERRORS)
def acknowledge_revision(
        assignment_id: str, body: AcknowledgeRevisionIn, response: Response,
        user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
        connection=Depends(get_connection)):
    """Operator only: records exactly their own acknowledgement, never changes assignment/capture."""
    response.headers["Cache-Control"] = "private, no-store"
    return revision_notices.acknowledge_revision(
        connection, actor_id=user.user_id, assignment_id=assignment_id,
        expected_version=body.expected_version, sectors=user.sectors,
        machine_codes=visibility.authorized_production_machine_codes(connection, user),
        request_id=_request_id())


@router.get("/active", response_model=ActiveOut, responses=_ERRORS)
def active(machine_code: str = Query(max_length=64), user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_READ)),
           connection=Depends(get_connection)):
    """Asignación activa de la máquina (o null), turno actual y si la asignación quedó vencida (`stale`). Con 2+ activas: 409 MULTIPLE_ACTIVE_ASSIGNMENTS
    (usar /active-lines)."""
    return active_out(service.get_active(connection, machine_code=machine_code, sectors=user.sectors,
                                         machine_codes=visibility.legacy_scope(connection, user, "assignments.active")))


@router.get("/active-lines", response_model=ActiveLinesOut, responses=_ERRORS)
def active_lines(machine_code: str = Query(max_length=64), user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_READ)),
                 connection=Depends(get_connection)):
    """Todas las asignaciones activas de la máquina (varias líneas de una misma OT con la compuerta multimáquina), cada una con `stale`."""
    return active_lines_out(service.get_active_lines(connection, machine_code=machine_code, sectors=user.sectors,
                                                     machine_codes=visibility.operational_scope(connection, user)))


@router.get("/operational-lines", response_model=OperationalLinesOut, responses=_ERRORS)
def operational_lines(user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_READ)), connection=Depends(get_connection)):
    """Contrato operativo: todas las líneas activas de las máquinas AUTORIZADAS del usuario (Operación/Calidad: las de sus concesiones; Jefatura/Supervisión:
    las de su alcance por sector). Cada línea trae `assignment_id`, `stale` y `selectable`; el servidor nunca elige una."""
    return operational_lines_out(service.list_operational_lines(connection, sectors=user.sectors, machine_codes=visibility.operational_scope(connection, user)))


@router.get("", response_model=list[AssignmentOut], responses=_ERRORS)
def list_assignments(machine_code: str | None = Query(default=None, max_length=64), status: Literal["active", "finished"] | None = None,
                     operating_date: date | None = None, work_order_id: UUID | None = None,
                     limit: int = Query(default=service.DEFAULT_LIST_LIMIT, ge=1, le=service.MAX_LIST_LIMIT),
                     user: AuthenticatedUser = Depends(require_permission(ASSIGNMENT_READ)), connection=Depends(get_connection)):
    return [assignment_out(v) for v in service.list_assignments(connection, machine_code=machine_code, status=status,
                                                                  operating_date=operating_date, work_order_id=work_order_id, limit=limit, sectors=user.sectors,
                                                                  machine_codes=visibility.legacy_scope(connection, user, "assignments.list"))]
