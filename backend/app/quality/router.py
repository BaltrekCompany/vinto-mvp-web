"""Calidad: bandeja central de Bobinas (GET /api/quality/bobbins, solo lectura) y capturas de Calidad ligadas a una Bobina
(POST/GET /api/quality/bobbins/{bobbin_id}/captures, GET /api/quality/captures/{capture_id}). Permiso quality.capture, nunca production.capture.
Nada de esto libera ni rechaza: quality_release no se modifica."""

import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Response

from app.auth.dependencies import require_permission
from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.quality import capture_service, service
from app.quality.capture_schemas import QualityCaptureIn, QualityCaptureOut, QualityCaptureResultOut, quality_capture_out, quality_capture_result_out
from app.quality.schemas import QualityBobbinOut, quality_bobbin_out

router = APIRouter(prefix="/api/quality", tags=["Calidad"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (quality.capture)"},
    422: {"description": "Estado desconocido"},
}


@router.get("/bobbins", response_model=list[QualityBobbinOut], responses=_ERRORS)
def quality_bobbin_inbox(status: Literal["pending", "released", "rejected"] = service.DEFAULT_STATUS,
                         _user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    """Bobinas F3 cuyo quality_release tiene el estado pedido (por defecto `pending`), independientemente de la asignación vigente.
    El orden es solo de presentación (captura más reciente primero), NO una prioridad de negocio."""
    return [quality_bobbin_out(v) for v in service.list_quality_bobbins(connection, status)]


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
    result = capture_service.submit_quality_capture(
        connection, actor_id=user.user_id, bobbin_id=bobbin_id, capture_id=body.capture_id, form_code=body.form_code,
        device_key=body.device_key, values=body.values, request_id=str(uuid.uuid4()))
    response.status_code = 201 if result.created else 200
    return quality_capture_result_out(result)


@router.get("/bobbins/{bobbin_id}/captures", response_model=list[QualityCaptureOut], responses=_CAPTURE_ERRORS)
def list_bobbin_quality_captures(bobbin_id: str, _user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    return [quality_capture_out(v) for v in capture_service.list_bobbin_quality_captures(connection, bobbin_id)]


@router.get("/captures/{capture_id}", response_model=QualityCaptureOut, responses=_CAPTURE_ERRORS)
def get_quality_capture(capture_id: str, _user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)), connection=Depends(get_connection)):
    return quality_capture_out(capture_service.get_quality_capture(connection, capture_id))
