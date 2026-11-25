"""Authenticated opt-in preparation of Quality offline CAPTURE authority.

This endpoint is OFF by default. It only issues a short-lived signed grant to
a session user with a current effective Quality form grant AND a registered,
active server-side device. It is not the receiver; sync must reauthorize every
capture atomically and require a persisted ACK.
"""
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.auth.dependencies import require_permission
from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.engine import authorize
from app.authz.policies import Operation
from app.config import settings
from app.database import get_connection
from app.quality.offline_capture_scope import FORM_OPERATION, sign_quality_capture_scope

router = APIRouter(prefix="/api/offline/quality", tags=["Calidad offline"])
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
MACHINE = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")


class CapturePreparationRequest(BaseModel):
    device_key: uuid.UUID
    machine_code: str = Field(min_length=1, max_length=48)
    form_code: Literal[
        "VINTO-P1-18","VINTO-P1-19","VINTO-P1-20","VINTO-P1-21",
        "VINTO-P1-22","VINTO-P1-24","VINTO-P1-25","VINTO-P1-26",
        "VINTO-P1-27","VINTO-P1-28",
    ]


@router.post("/capture-authority")
def prepare_capture_authority(
    body: CapturePreparationRequest,
    response: Response,
    user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)),
    connection = Depends(get_connection),
):
    response.headers["Cache-Control"] = "no-store"
    # No feature flag can be provided by the browser; server settings only.
    if not settings.offline_quality_capture_enabled:
        raise HTTPException(status_code=503, detail="Calidad offline no habilitada")
    secret = settings.offline_quality_signing_seed_hex
    if secret is None or not secret.get_secret_value():
        raise HTTPException(status_code=503, detail="Calidad offline no disponible")

    machine = body.machine_code.strip()
    device_key = str(body.device_key)
    if machine != body.machine_code or not MACHINE.fullmatch(machine) or not UUID4.fullmatch(device_key):
        raise HTTPException(status_code=422, detail="Contexto offline inválido")

    operation = Operation(FORM_OPERATION[body.form_code])
    # The issued signature is only a short-lived CAPTURE credential; it
    # cannot sidestep effective auth, active grants, or published form versions.
    with connection.transaction():
        connection.execute("SET TRANSACTION READ ONLY")
        registered = connection.execute(
            "SELECT active FROM vinto_master.device WHERE external_key = %s",
            (device_key,),
        ).fetchone()
        if registered is None or not registered[0]:
            raise HTTPException(status_code=403, detail="Dispositivo no habilitado")
        decision = authorize(connection, user, operation, machine, body.form_code, lock=False)
        if not decision.allowed or decision.grant_id is None or decision.effective_version is None:
            raise HTTPException(status_code=403, detail="Permiso insuficiente")
        entry = {
            "machine_code":machine,
            "form_code":body.form_code,
            "form_version":decision.effective_version,
            "operation":operation.value,
            "grant_id":str(decision.grant_id),
        }
    # Secrets are read only from protected server settings, never the request.
    return sign_quality_capture_scope(
        signing_seed_hex=secret.get_secret_value(),
        subject_user_id=str(user.user_id),
        device_key=device_key,
        form_scopes=[entry],
    )
