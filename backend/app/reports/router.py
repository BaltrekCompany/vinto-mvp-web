"""GET /api/reports/tubetes-used: read-only MP1/MP3 tubete usage report."""

import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.dependencies import require_permission
from app.auth.permissions import REPORT_READ
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.reports.tubetes_schemas import TubetesReportOut
from app.reports.tubetes_service import (
    TubetesReportDataError,
    TubetesReportForbiddenError,
    get_tubetes_report,
)

logger = logging.getLogger("uvicorn.error")
router = APIRouter(prefix="/api/reports", tags=["Reportes"])


@router.get(
    "/tubetes-used",
    response_model=TubetesReportOut,
    responses={
        401: {"description": "No autenticado"},
        403: {"description": "Permiso report.read o sector BOBINAS insuficiente"},
        503: {"description": "Reporte no disponible"},
    },
)
def tubetes_used_report(
    user: AuthenticatedUser = Depends(require_permission(REPORT_READ)),
    connection=Depends(get_connection),
):
    """Return both Bobinas machines; scope and machine filters are server-owned."""
    try:
        return get_tubetes_report(connection, sectors=user.sectors)
    except TubetesReportForbiddenError:
        raise HTTPException(status_code=403, detail="Permiso insuficiente") from None
    except TubetesReportDataError:
        # Never include source values, capture IDs or SQL in the public response/log.
        logger.warning("Tubetes report unavailable: P1-03 source data contract mismatch")
        raise HTTPException(status_code=503, detail="Reporte no disponible") from None
