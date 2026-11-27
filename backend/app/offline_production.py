"""FOFF-02B: consulta de preparación para producción offline, SOLO LECTURA.

No enrola, emite autoridad CAPTURE, almacena secretos ni habilita envío offline.
La lista de formularios proviene del mismo contrato y motor de elegibilidad
que utiliza Ejecución online; sin concesión efectiva no hay oferta.
"""
import re
import uuid

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.auth.dependencies import require_permission
from app.auth.permissions import PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.production_access import production_machines
from app import capture_service as central_captures
from app.config import settings
from app.sectors import SECTOR_CONVERSION, SECTOR_REBOBINADO, SECTOR_BOBINAS

router = APIRouter(prefix="/api/offline/production", tags=["Preparación producción offline"])


@router.get("/offers")
def list_offline_production_offers(
    response: Response,
    user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
    connection=Depends(get_connection),
):
    response.headers["Cache-Control"] = "private, no-store"
    availability = production_machines(connection, user.sectors, user=user)
    offers = []
    for sector in availability.sectors:
        if sector.code not in (SECTOR_CONVERSION, SECTOR_REBOBINADO, SECTOR_BOBINAS):
            continue
        for machine in sector.machines:
            for form in [*machine.forms, *(machine.bobbin_forms or [])]:
                if form.eligible is not True:
                    continue
                offers.append({
                    "sectorCode": sector.code,
                    "machineCode": machine.code,
                    "machineName": machine.name,
                    "formCode": form.code,
                    "formName": form.name,
                    "formVersion": form.version_number,
                })
    return {"offers": offers, "captureEnabled": False}


class ProductionEnrollmentIn(BaseModel):
    device_key: uuid.UUID


@router.post("/enroll")
def enroll_production_device(
    body: ProductionEnrollmentIn,
    response: Response,
    user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
    connection=Depends(get_connection),
):
    """Enrollment only; never creates an offline capture authority or uploads a capture.

    Reuses the central device registry and refuses inactive device keys.
    Requires at least one effective production grant, not just a broad role.
    """
    response.headers["Cache-Control"] = "no-store"
    if not settings.offline_production_enrollment_enabled:
        raise HTTPException(status_code=503, detail="Preparación offline de producción no habilitada")
    device_key = str(body.device_key)
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", device_key, re.I):
        raise HTTPException(status_code=422, detail="Dispositivo inválido")
    availability = production_machines(connection, user.sectors, user=user)
    has_grant = any(
        form.eligible is True
        for sector in availability.sectors
        if sector.code in (SECTOR_CONVERSION, SECTOR_REBOBINADO, SECTOR_BOBINAS)
        for machine in sector.machines
        for form in [*machine.forms, *(machine.bobbin_forms or [])]
    )
    if not has_grant:
        raise HTTPException(status_code=403, detail="No hay formularios autorizados")
    with connection.transaction():
        central_captures._context(connection, user.user_id, str(uuid.uuid4()))
        central_captures._resolve_device(connection, device_key, None)
    return {"device_key": device_key, "enrolled": True, "captureEnabled": False}
