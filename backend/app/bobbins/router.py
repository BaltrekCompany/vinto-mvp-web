"""POST /api/bobbins (F3: captura + bobina + quality_release pending) y GET /api/bobbins/{id}. El contrato HTTP de F6 no cambia."""

import uuid

from fastapi import APIRouter, Depends, Response

from app.auth.dependencies import require_permission
from app.auth.permissions import PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.capture_gate import gate_for
from app.authz.policies import Operation
from app.bobbins import service
from app.bobbins.schemas import BobbinIn, BobbinOut, BobbinResultOut, bobbin_out, result_out
from app.config import settings
from app.database import get_connection

router = APIRouter(prefix="/api/bobbins", tags=["Bobinas"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (production.capture) o acceso no autorizado a la máquina para P1-03 (modo enforce)"},
    404: {"description": "Asignación o bobina inexistente"},
    409: {"description": "Estado, contexto o idempotencia en conflicto"},
    422: {"description": "Valores inválidos"},
    503: {"description": "Autorización no disponible (modo enforce)"},
}


@router.post("", response_model=BobbinResultOut, responses={201: {"description": "Bobina creada"}, **_ERRORS})
def register_bobbin(body: BobbinIn, response: Response, user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
                    connection=Depends(get_connection)):
    """201 si se creó; 200 con already_submitted si es un reintento idéntico (idempotente por capture_id)."""
    request_id = str(uuid.uuid4())
    # MF-13-01D.2B: la autorización efectiva de F3 depende SOLO de su propio modo de servidor (por defecto off = comportamiento anterior); el cliente no puede cambiarlo.
    gate = gate_for(user, settings.authz_bobbin_production_mode, request_id, Operation.BOBBIN_PRODUCTION)
    result = service.submit_bobbin_production(
        connection, actor_id=user.user_id, capture_id=body.capture_id, assignment_id=body.assignment_id, device_key=body.device_key,
        values=body.values.model_dump(exclude_none=True), request_id=request_id, sectors=user.sectors, gate=gate)
    response.status_code = 201 if result.created else 200
    return result_out(result)


@router.get("/{bobbin_id}", response_model=BobbinOut, responses=_ERRORS)
def get_bobbin(bobbin_id: str, user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)), connection=Depends(get_connection)):
    return bobbin_out(service.get_bobbin(connection, bobbin_id, sectors=user.sectors))
