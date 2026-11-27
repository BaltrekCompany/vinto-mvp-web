"""FOFF-02B: consulta de preparación para producción offline, SOLO LECTURA.

No enrola, emite autoridad CAPTURE, almacena secretos ni habilita envío offline.
La lista de formularios proviene del mismo contrato y motor de elegibilidad
que utiliza Ejecución online; sin concesión efectiva no hay oferta.
"""
from fastapi import APIRouter, Depends, Response

from app.auth.dependencies import require_permission
from app.auth.permissions import PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.production_access import production_machines

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
        if sector.code not in ("CONVERSION", "REBOBINADO", "BOBINAS"):
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
