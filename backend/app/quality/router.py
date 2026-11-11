"""Calidad: bandeja central de Bobinas (GET /api/quality/bobbins, solo lectura) y capturas de Calidad ligadas a una Bobina
(POST/GET /api/quality/bobbins/{bobbin_id}/captures, GET /api/quality/captures/{capture_id}). Permiso quality.capture, nunca production.capture.
Las capturas nunca liberan/rechazan; el endpoint /decision es una operacion independiente auditada."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Query, Response

from app.auth.dependencies import require_permission
from app.auth.permissions import QUALITY_CAPTURE, QUALITY_RELEASE
from app.auth.service import AuthenticatedUser
from app.authz.capture_gate import gate_for
from app.authz.policies import Operation
from app.config import settings
from app.database import get_connection
from app.quality import capture_service, service, decision_service
from app.quality.decision_schemas import QualityDecisionIn, QualityDecisionOut
from app.quality.capture_schemas import QualityCaptureIn, QualityCaptureOut, QualityCaptureResultOut, quality_capture_out, quality_capture_result_out
from app.production_access import ProductionMachinesOut
from app.quality.schemas import QualityBobbinOut, quality_bobbin_out

router = APIRouter(prefix="/api/quality", tags=["Calidad"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (quality.capture)"},
    422: {"description": "Estado desconocido"},
}


@router.get("/bobbins", response_model=list[QualityBobbinOut], responses=_ERRORS)
def quality_bobbin_inbox(status: Literal["pending", "released", "rejected"] = service.DEFAULT_STATUS,
                         include_rewinding_family: bool = Query(default=False),
                         user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    """Bobinas F3 cuyo quality_release tiene el estado pedido (por defecto `pending`), independientemente de la asignación vigente.
    El orden es solo de presentación (captura más reciente primero), NO una prioridad de negocio."""
    return [quality_bobbin_out(v) for v in service.list_quality_bobbins(
        connection, status, sectors=user.sectors, include_rewinding_family=include_rewinding_family)]


# ---- capturas de Calidad ligadas a una Bobina (fundación) -------------------------------------------------------------------

_CAPTURE_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (quality.capture)"},
    404: {"description": "Bobina o captura inexistente"},
    409: {"description": "Formulario no disponible, contexto o idempotencia en conflicto"},
    422: {"description": "Payload o valores inválidos"},
}


@router.post("/bobbins/{bobbin_id}/captures", response_model=QualityCaptureResultOut, responses={201: {"description": "Captura creada"}, **_CAPTURE_ERRORS})
def submit_quality_capture(bobbin_id: str, body: QualityCaptureIn, response: Response,
                           user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    """201 si se creó; 200 con already_submitted si es un reintento idéntico (idempotente por capture_id). No toca quality_release."""
    request_id = str(uuid.uuid4())
    # MF-13-01D.2C.1: la autorización efectiva de Calidad por bobina depende SOLO de su propio modo de servidor (por defecto off = comportamiento anterior); el cliente no puede cambiarlo.
    gate = gate_for(user, settings.authz_quality_bobbin_captures_mode, request_id, Operation.QUALITY_BOBBIN_CAPTURE)
    result = capture_service.submit_quality_capture(
        connection, actor_id=user.user_id, bobbin_id=bobbin_id, capture_id=body.capture_id, form_code=body.form_code,
        device_key=body.device_key, values=body.values, request_id=request_id, sectors=user.sectors, gate=gate)
    response.status_code = 201 if result.created else 200
    return quality_capture_result_out(result)


@router.get("/bobbin-forms", response_model=ProductionMachinesOut, response_model_exclude_none=True, responses={401: _ERRORS[401], 403: _ERRORS[403]})
def bobbin_candidate_forms(user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    """Máquinas del alcance y candidatos de Calidad por Bobina (DEV-Q2) que el backend publica (vacío con la política real)."""
    return {"sectors": capture_service.available_bobbin_forms(connection, sectors=user.sectors, user=user)}


@router.get("/bobbins/{bobbin_id}/captures", response_model=list[QualityCaptureOut], responses=_CAPTURE_ERRORS)
def list_bobbin_quality_captures(bobbin_id: str, form_code: str | None = Query(default=None, min_length=1, max_length=64),
                                 user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    return [quality_capture_out(v) for v in capture_service.list_bobbin_quality_captures(connection, bobbin_id, form_code=form_code, sectors=user.sectors)]


@router.get("/captures/{capture_id}", response_model=QualityCaptureOut, responses=_CAPTURE_ERRORS)
def get_quality_capture(capture_id: str, user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    return quality_capture_out(capture_service.get_quality_capture(connection, capture_id, sectors=user.sectors))


@router.post("/bobbins/{bobbin_id}/decision", response_model=QualityDecisionOut,
             responses={401: {"description": "No autenticado"}, 403: {"description": "Sin permiso quality.release"},
                        404: {"description": "Bobina inexistente o fuera de alcance"}, 409: {"description": "Ya decidida"},
                        422: {"description": "Datos de decision invalidos"}})
def decide_quality_bobbin(bobbin_id: uuid.UUID, body: QualityDecisionIn,
                          user: AuthenticatedUser = Depends(require_permission(QUALITY_RELEASE)),
                          connection=Depends(get_connection)):
    """Decide una bobina F3 numerada en Bobinas/Rebobinado, independientemente de la OT o turno.
    Un reintento con decision_id identico devuelve 200; uno diferente devuelve 409."""
    return decision_service.decide_bobbin(
        connection, bobbin_id=bobbin_id, actor_id=user.user_id, sectors=user.sectors,
        request_id=str(uuid.uuid4()), body=body)
