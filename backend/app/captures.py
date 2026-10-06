"""Capturas: contador de seguimiento (GET /count) y capturas de producción F6 (POST, listado y detalle)."""

import uuid
from datetime import date
from typing import Literal
from uuid import UUID

import psycopg
from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app import capture_service
from app.auth.dependencies import require_permission
from app.auth.permissions import PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.capture_schemas import CaptureIn, CaptureOut, CaptureResultOut, capture_out, result_out
from app.config import settings
from app.database import DatabaseUnavailable, get_connection, logger

Front = Literal["Bobinas", "Rebobinado", "Conversión", "Calidad"]
router = APIRouter(prefix="/api/captures", tags=["Seguimiento"])


class CaptureCount(BaseModel):
    front: Front
    count: int = Field(ge=0)
    source: Literal["database"] = "database"


def capture_count_query(front: Front) -> tuple[str, tuple[str]]:
    if front == "Calidad":
        return ("""SELECT count(*) FROM vinto_txn.capture c
                JOIN vinto_config.form_version f ON f.id = c.form_version_id
                WHERE f.area = %s""", ("quality",))
    return ("""SELECT count(*) FROM vinto_txn.capture c
            JOIN vinto_master.machine m ON m.id = c.machine_id
            JOIN vinto_master.sector s ON s.id = m.sector_id
            WHERE s.name = %s""", (front,))


def count_captures(front: Front) -> int:
    if settings.database_url is None or not settings.database_url.get_secret_value():
        logger.warning("Capture count: DATABASE_URL no está configurada")
        raise DatabaseUnavailable("Database unavailable")
    try:
        with psycopg.connect(
            settings.database_url.get_secret_value(),
            connect_timeout=settings.db_connect_timeout,
            options=f"-c statement_timeout={settings.db_statement_timeout_ms}",
        ) as connection:
            connection.read_only = True
            result = connection.execute(*capture_count_query(front)).fetchone()
            return result[0]
    except (psycopg.Error, ValueError) as error:
        logger.warning("Capture count: consulta no disponible (%s)", type(error).__name__)
        raise DatabaseUnavailable("Database unavailable") from None


@router.get("/count", response_model=CaptureCount, responses={503: {"description": "Consulta no disponible"}})
def capture_count(front: Front):
    try:
        return CaptureCount(front=front, count=count_captures(front))
    except DatabaseUnavailable:
        return JSONResponse(status_code=503, content={"status": "error", "database": "unavailable"})


# ---- capturas de producción F6 (VINTO-P1-06) ---------------------------------------------------------------------
# /count se declara primero: "count" no debe interpretarse como un {capture_id}.

_CAPTURE_ERRORS = {
    401: {"description": "No autenticado"},
    403: {"description": "Permiso insuficiente (production.capture)"},
    404: {"description": "Asignación o captura inexistente"},
    409: {"description": "Estado, contexto o idempotencia en conflicto"},
    422: {"description": "Valores inválidos"},
}


@router.post("", response_model=CaptureResultOut, responses={201: {"description": "Captura creada"}, **_CAPTURE_ERRORS})
def submit_capture(body: CaptureIn, response: Response, user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
                   connection=Depends(get_connection)):
    """201 si se creó; 200 con already_submitted si es un reintento idéntico (idempotente por capture_id)."""
    result = capture_service.submit_production_capture(
        connection, actor_id=user.user_id, capture_id=body.capture_id, form_code=body.form_code, assignment_id=body.assignment_id,
        device_key=body.device_key, values=body.values, request_id=str(uuid.uuid4()))
    response.status_code = 201 if result.created else 200
    return result_out(result)


@router.get("", response_model=list[CaptureOut], responses=_CAPTURE_ERRORS)
def list_captures(assignment_id: UUID | None = None, machine_code: str | None = Query(default=None, max_length=64), operating_date: date | None = None,
                  limit: int = Query(default=capture_service.DEFAULT_LIST_LIMIT, ge=1, le=capture_service.MAX_LIST_LIMIT),
                  _user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)), connection=Depends(get_connection)):
    return [capture_out(v) for v in capture_service.list_captures(connection, assignment_id=assignment_id, machine_code=machine_code,
                                                                   operating_date=operating_date, limit=limit)]


@router.get("/{capture_id}", response_model=CaptureOut, responses=_CAPTURE_ERRORS)
def get_capture(capture_id: str, _user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)), connection=Depends(get_connection)):
    return capture_out(capture_service.get_capture(connection, capture_id))
