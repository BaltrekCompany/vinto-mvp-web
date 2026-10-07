"""GET /api/quality/bobbins: bandeja central de Calidad (solo lectura). Permiso quality.capture, nunca production.capture."""

from typing import Literal

from fastapi import APIRouter, Depends

from app.auth.dependencies import require_permission
from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.quality import service
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
