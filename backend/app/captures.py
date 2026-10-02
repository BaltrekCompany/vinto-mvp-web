"""Consulta de seguimiento; no escribe ni importa capturas locales."""

from typing import Literal

import psycopg
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from app.config import settings
from app.database import DatabaseUnavailable, logger

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
