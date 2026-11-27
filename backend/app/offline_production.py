"""FOFF-02B: consulta de preparación para producción offline, SOLO LECTURA.

No enrola, emite autoridad CAPTURE, almacena secretos ni habilita envío offline.
La lista de formularios proviene del mismo contrato y motor de elegibilidad
que utiliza Ejecución online; sin concesión efectiva no hay oferta.
"""
import re
import uuid
import hashlib

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from app.auth.dependencies import require_permission
from app.auth.permissions import PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.database import get_connection
from app.production_access import production_machines
from app.foff_conversion_preparation import sign_conversion_preparation, conversion_preparation_public_pin, CONVERSION_CODES
from app.foff_conversion_references import conversion_reference_bundle, ConversionReferencesUnavailable
from app.assignments import service as assignment_service, execution_read
from app.authz import visibility
from app.authz.engine import authorize
from app.authz.policies import Operation
from app.quality.offline_capture_scope import _canonical
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
    # Public pin is delivered only over this authenticated enrollment response.
    # The client must store/pin it in its own encrypted device profile and
    # reject an envelope whose embedded key differs from this pin.
    seed = settings.offline_conversion_preparation_signing_seed_hex
    pin = conversion_preparation_public_pin(seed.get_secret_value()) if seed else None
    return {"device_key": device_key, "enrolled": True,
            "preparation_signing_pin": pin, "captureEnabled": False}


class ConversionPreparationIn(BaseModel):
    device_key: uuid.UUID
    assignment_id: uuid.UUID
    form_code: str


@router.post("/conversion/prepare")
def prepare_conversion_context(
    body: ConversionPreparationIn,
    response: Response,
    user: AuthenticatedUser = Depends(require_permission(PRODUCTION_CAPTURE)),
    connection=Depends(get_connection),
):
    """Read-only and fail closed. Does not issue CAPTURE authority."""
    response.headers["Cache-Control"] = "no-store"
    if not settings.offline_conversion_preparation_enabled:
        raise HTTPException(status_code=503, detail="Preparación de Conversión no habilitada")
    seed = settings.offline_conversion_preparation_signing_seed_hex
    if seed is None or not re.fullmatch(r"[a-fA-F0-9]{64}", seed.get_secret_value()):
        raise HTTPException(status_code=503, detail="Firma de preparación no disponible")
    if body.form_code not in CONVERSION_CODES:
        raise HTTPException(status_code=422, detail="Formulario no admitido")
    device_key = str(body.device_key)
    if not re.fullmatch(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}", device_key, re.I):
        raise HTTPException(status_code=422, detail="Dispositivo inválido")
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        device = connection.execute(
            "SELECT active FROM vinto_master.device WHERE external_key=%s",
            (device_key,),
        ).fetchone()
        if device is None or device[0] is not True:
            raise HTTPException(status_code=403, detail="Dispositivo no habilitado")
        machine_scope = visibility.authorized_production_machine_codes(connection, user)
        candidates = assignment_service.list_operational_lines(
            connection, sectors=user.sectors, machine_codes=machine_scope)
        matched = [item for item in candidates if str(item.assignment.id) == str(body.assignment_id)]
        if len(matched) != 1 or matched[0].stale is not False:
            raise HTTPException(status_code=409, detail="Asignación no disponible")
        a = matched[0].assignment
        if a.status != "active":
            raise HTTPException(status_code=409, detail="Asignación no activa")
        if settings.work_order_line_execution_enabled:
            status = execution_read.read_machine_execution(
                connection, machine_code=a.machine_code, sectors=user.sectors,
                machine_codes=machine_scope)
            if not any(str(x["assignment_id"]) == str(a.id) and x["status"] == "in_production"
                       for x in status["assignments"]):
                raise HTTPException(status_code=409, detail="Línea no iniciada")
        decision = authorize(connection, user, Operation.PRODUCTION_CAPTURE,
                             a.machine_code, body.form_code, lock=False)
        if not decision.allowed or decision.grant_id is None or decision.effective_version is None:
            raise HTTPException(status_code=403, detail="Concesión no vigente")
        # Timestamp and effective operational shift are server-managed.
        context = {
            "assignment_id": str(a.id),
            "work_order_id": str(a.work_order_id),
            "line_id": str(a.line.id),
            "machine_code": a.machine_code,
            "form_code": body.form_code,
            "form_version": decision.effective_version,
            "article_code": a.line.article_code,
            "shift_code": a.shift_code,
            "operating_date": a.operating_date.isoformat(),
        }
        try:
            machine_row = connection.execute(
                "SELECT id FROM vinto_master.machine WHERE code=%s AND active=true",
                (a.machine_code,),
            ).fetchone()
            if machine_row is None:
                raise ConversionReferencesUnavailable("machine_unavailable")
            reference_package = conversion_reference_bundle(
                connection,
                machine_id=machine_row[0],
                machine_code=a.machine_code,
                article_code=a.line.article_code,
                form_code=body.form_code,
                form_version=decision.effective_version,
            )
        except ConversionReferencesUnavailable:
            raise HTTPException(status_code=409, detail="Referencias de formulario no disponibles")
        context["reference_sha256"] = reference_package["sha256"]
        digest = hashlib.sha256(_canonical(context)).hexdigest()
        signed_context = {**context, "context_digest": digest}
    envelope = sign_conversion_preparation(
        seed_hex=seed.get_secret_value(), user_id=str(user.user_id),
        device_key=device_key, context=signed_context,
    )
    return {"envelope": envelope, "referencePackage": reference_package["bundle"], "captureEnabled": False}
