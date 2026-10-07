"""POST /api/bobbins (F3: captura + bobina + quality_release pending) y GET /api/bobbins/{id}. El contrato HTTP de F6 no cambia."""

import uuid

from fastapi import APIRouter, Depends, Response

from app.auth.dependencies import require_permission
from app.auth.permissions import PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.bobbins import service
from app.bobbins.schemas import BobbinIn, BobbinOut, BobbinResultOut, bobbin_out, result_out
from app.database import get_connection

router = APIRouter(prefix="/api/bobbins", tags=["Bobinas"])

_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (production.capture)"},
    404: {"description": "Asignación o bobina inexistente"},
    409: {"description": "Estado, contexto o idempotencia en conflicto"},
    422: {"description": "Valores inválidos"},
}


@router.post("", response_model=BobbinResultOut, responses={201: {"description": "Bobina creada"}, **_ERRORS})
def register_bobbin(body: BobbinIn, response: Response, user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
                    connection=Depends(get_connection)):
    """201 si se creó; 200 con already_submitted si es un reintento idéntico (idempotente por capture_id)."""
    result = service.submit_bobbin_production(
        connection, actor_id=user.user_id, capture_id=body.capture_id, assignment_id=body.assignment_id, device_key=body.device_key,
        values=body.values.model_dump(exclude_none=True), request_id=str(uuid.uuid4()))
    response.status_code = 201 if result.created else 200
    return result_out(result)


@router.get("/{bobbin_id}", response_model=BobbinOut, responses=_ERRORS)
def get_bobbin(bobbin_id: str, _user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)), connection=Depends(get_connection)):
    return bobbin_out(service.get_bobbin(connection, bobbin_id))
