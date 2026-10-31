"""Controles de Calidad POR MÁQUINA (DEV-Q1, candidato): disponibilidad, POST idempotente, GET por id y listado filtrado. Permiso quality.capture (nunca production.capture); alcance por concesión de sector.
No requiere Bobina ni asignación, no usa el endpoint de Producción y no modifica los controles por Bobina. Nada de esto libera ni rechaza: quality_release no se modifica."""

import uuid

from fastapi import APIRouter, Depends, Query, Response

from app.auth.dependencies import require_permission
from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.capture_gate import gate_for
from app.authz.policies import Operation
from app.config import settings
from app.database import get_connection
from app.production_access import ProductionMachinesOut
from app.quality import machine_capture_service as service
from app.quality.machine_capture_schemas import MachineCaptureIn, MachineCaptureOut, MachineCaptureResultOut, machine_capture_out, machine_capture_result_out

router = APIRouter(prefix="/api/quality", tags=["Calidad por máquina"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (quality.capture)"},
    404: {"description": "Máquina o captura inexistente"},
    409: {"description": "Formulario no disponible o idempotencia en conflicto"},
    422: {"description": "Payload, formulario o valores inválidos"},
}


@router.get("/machine-forms", response_model=ProductionMachinesOut, response_model_exclude_none=True, responses=_ERRORS)
def machine_forms(user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    """Máquinas del alcance y formularios de Calidad por máquina que el backend publica (vacío con la política real)."""
    return {"sectors": service.available_forms(connection, user.sectors)}


@router.post("/machines/{machine_code}/captures", response_model=MachineCaptureResultOut, responses={201: {"description": "Control creado"}, **_ERRORS})
def submit_machine_capture(machine_code: str, body: MachineCaptureIn, response: Response, user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    """201 si se creó; 200 con already_submitted si es un reintento idéntico (idempotente por capture_id)."""
    request_id = str(uuid.uuid4())
    # MF-13-01D.2C.2: la autorización efectiva de Calidad por máquina depende SOLO de su propio modo de servidor (por defecto off = comportamiento anterior); el cliente no puede cambiarlo.
    gate = gate_for(user, settings.authz_quality_machine_captures_mode, request_id, Operation.QUALITY_MACHINE_CAPTURE)
    result = service.submit_machine_capture(connection, actor_id=user.user_id, machine_code=machine_code, capture_id=body.capture_id, form_code=body.form_code,
                                            device_key=body.device_key, values=body.values, request_id=request_id, sectors=user.sectors, gate=gate)
    response.status_code = 201 if result.created else 200
    return machine_capture_result_out(result)


@router.get("/machines/{machine_code}/captures", response_model=list[MachineCaptureOut], responses=_ERRORS)
def list_machine_captures(machine_code: str, form_code: str | None = Query(default=None, min_length=1, max_length=64), limit: int = Query(default=service.DEFAULT_LIST_LIMIT, ge=1, le=service.MAX_LIST_LIMIT),
                          user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    return [machine_capture_out(v) for v in service.list_machine_captures(connection, machine_code, form_code=form_code, limit=limit, sectors=user.sectors)]


@router.get("/machine-captures/{capture_id}", response_model=MachineCaptureOut, responses=_ERRORS)
def get_machine_capture(capture_id: str, user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    return machine_capture_out(service.get_machine_capture(connection, capture_id, sectors=user.sectors))
