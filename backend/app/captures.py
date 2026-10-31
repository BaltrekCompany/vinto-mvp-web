"""Capturas: contador de seguimiento (GET /count) y capturas de producción centrales (POST, listado y detalle; hoy solo F6)."""

import uuid
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response
from pydantic import BaseModel, Field

from app import capture_service
from app.auth.dependencies import require_permission
from app.auth.permissions import CATALOG_READ, PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.capture_gate import gate_for
from app.capture_schemas import CaptureIn, CaptureOut, CaptureResultOut, capture_out, result_out
from app.config import settings
from app.database import get_connection
from app.sectors import FRONT_SECTOR_CODES, scoped_sector_codes

Front = Literal["Bobinas", "Rebobinado", "Conversión", "Calidad"]
router = APIRouter(prefix="/api/captures", tags=["Seguimiento"])


class CaptureCount(BaseModel):
    front: Front
    count: int = Field(ge=0)
    source: Literal["database"] = "database"


def capture_count_query(front: Front, sectors) -> tuple[str, tuple]:
    """Conteo agregado limitado SIEMPRE a los sectores visibles (operativos ∩ concedidos al usuario), por código de sector.

    - Bobinas / Rebobinado / Conversión: capturas de máquinas de ese sector (si no está entre los visibles, el conteo es 0).
    - Calidad: capturas de formularios con área quality, solo de máquinas de los sectores visibles.
    Nunca se filtra por el nombre visible del sector. Con alcance vacío ambos devuelven 0.
    """
    visible = list(scoped_sector_codes(sectors))
    if front == "Calidad":
        return ("""SELECT count(*) FROM vinto_txn.capture c
                JOIN vinto_config.form_version f ON f.id = c.form_version_id
                JOIN vinto_master.machine m ON m.id = c.machine_id
                JOIN vinto_master.sector s ON s.id = m.sector_id
                WHERE f.area = %s AND s.code = ANY(%s)""", ("quality", visible))
    return ("""SELECT count(*) FROM vinto_txn.capture c
            JOIN vinto_master.machine m ON m.id = c.machine_id
            JOIN vinto_master.sector s ON s.id = m.sector_id
            WHERE s.code = %s AND s.code = ANY(%s)""", (FRONT_SECTOR_CODES[front], visible))


def count_captures(connection, front: Front, sectors) -> int:
    """Una consulta de solo lectura sobre la conexión de la petición (la misma que resolvió la sesión)."""
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        return connection.execute(*capture_count_query(front, sectors)).fetchone()[0]


@router.get("/count", response_model=CaptureCount, responses={401: {"description": "No autenticado"}, 403: {"description": "Permiso insuficiente (catalog.read)"},
                                                              503: {"description": "Consulta no disponible"}})
def capture_count(front: Front, user: AuthenticatedUser = Depends(require_permission(CATALOG_READ)), connection=Depends(get_connection)):
    """Conteo agregado de capturas por frente. Exige sesión y `catalog.read` (lectura de estadísticas: no concede capturar) y solo cuenta los
    sectores operativos concedidos a la sesión; el cliente no puede ampliar el alcance. No escribe nada."""
    return CaptureCount(front=front, count=count_captures(connection, front, user.sectors))


# ---- capturas de producción centrales (formularios de capture_service.CENTRAL_FORM_CODES; hoy F6 / VINTO-P1-06) ---------------------------------------------------------------------
# /count se declara primero: "count" no debe interpretarse como un {capture_id}.

_CAPTURE_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (production.capture) o acceso no autorizado a la máquina y el formulario (modo enforce)"},
    404: {"description": "Asignación o captura inexistente"},
    409: {"description": "Estado, contexto o idempotencia en conflicto"},
    422: {"description": "Valores inválidos"},
    503: {"description": "Autorización no disponible (modo enforce)"},
}


@router.post("", response_model=CaptureResultOut, responses={201: {"description": "Captura creada"}, **_CAPTURE_ERRORS})
def submit_capture(body: CaptureIn, response: Response, user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
                   connection=Depends(get_connection)):
    """201 si se creó; 200 con already_submitted si es un reintento idéntico (idempotente por capture_id)."""
    request_id = str(uuid.uuid4())
    # MF-13-01D.2A: la autorización efectiva depende SOLO del modo configurado en el servidor (por defecto off = comportamiento anterior); el cliente no puede cambiarlo.
    gate = gate_for(user, settings.authz_central_captures_mode, request_id)
    result = capture_service.submit_production_capture(
        connection, actor_id=user.user_id, capture_id=body.capture_id, form_code=body.form_code, assignment_id=body.assignment_id,
        device_key=body.device_key, values=body.values, request_id=request_id, sectors=user.sectors, gate=gate)
    response.status_code = 201 if result.created else 200
    return result_out(result)


@router.get("", response_model=list[CaptureOut], responses=_CAPTURE_ERRORS)
def list_captures(assignment_id: UUID | None = None, machine_code: str | None = Query(default=None, max_length=64), operating_date: date | None = None,
                  form_code: str | None = Query(default=None, max_length=64),
                  limit: int = Query(default=capture_service.DEFAULT_LIST_LIMIT, ge=1, le=capture_service.MAX_LIST_LIMIT),
                  user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)), connection=Depends(get_connection)):
    return [capture_out(v) for v in capture_service.list_captures(connection, assignment_id=assignment_id, machine_code=machine_code,
                                                                   operating_date=operating_date, limit=limit, form_code=form_code, sectors=user.sectors)]


@router.get("/{capture_id}", response_model=CaptureOut, responses=_CAPTURE_ERRORS)
def get_capture(capture_id: str, user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)), connection=Depends(get_connection)):
    return capture_out(capture_service.get_capture(connection, capture_id, sectors=user.sectors))
