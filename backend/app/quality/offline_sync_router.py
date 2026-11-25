"""VINTO: operational receipt only AFTER the normal Quality service commits.

OFF by default. No new capture table, no second business truth and no release
actions. The normal quality services own validation/idempotency and PostgreSQL
transactions. GET reconciles a lost HTTP ACK against the persisted capture.
This receiver intentionally does not implement offline enrollment or UX.
"""
import hashlib
import json
import re
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from app.auth.dependencies import require_permission
from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.capture_gate import gate_for
from app.authz.engine import authorize
from app.authz.policies import Operation
from app.config import settings
from app.database import get_connection
from app.quality import capture_service, machine_capture_service
from app.quality.offline_capture_scope import FORM_OPERATION, _canonical

router = APIRouter(prefix="/api/offline/captures", tags=["Calidad offline"])
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
SHA = re.compile(r"^[0-9a-f]{64}$")


class OfflineQualityCaptureIn(BaseModel):
    capture_id: uuid.UUID
    author_user_id: uuid.UUID
    device_key: uuid.UUID
    form_code: str
    form_version: int = Field(gt=0)
    context_version: str = Field(min_length=1, max_length=256)
    machine_code: str = Field(min_length=1, max_length=48)
    scope_snapshot_id: uuid.UUID
    payload_sha256: str
    payload: dict[str, Any]


def _enabled():
    if not settings.offline_quality_capture_enabled:
        raise HTTPException(status_code=503, detail="Calidad offline no habilitada")


def _validate_capture(body: OfflineQualityCaptureIn, user: AuthenticatedUser) -> tuple[dict, str | None]:
    if str(body.author_user_id) != str(user.user_id) or not UUID4.fullmatch(str(body.device_key)) or (
        not UUID4.fullmatch(str(body.scope_snapshot_id))):
        raise HTTPException(status_code=403, detail="Autor o dispositivo no autorizado")
    op = FORM_OPERATION.get(body.form_code)
    if op is None or not SHA.fullmatch(body.payload_sha256):
        raise HTTPException(status_code=422, detail="Captura offline inválida")
    value = body.payload
    if set(value) not in ({"synthetic", "payload"}, {"synthetic", "payload", "bobbin"}) or (
        value.get("synthetic") is not False) or not isinstance(value.get("payload"), dict):
        raise HTTPException(status_code=422, detail="Contenido offline inválido")
    if any(not isinstance(k, str) or not isinstance(v, (str,bool)) for k,v in value["payload"].items()):
        raise HTTPException(status_code=422, detail="Mediciones offline inválidas")
    bobbin_id: str | None = None
    if op == "quality_bobbin_capture":
        bobbin = value.get("bobbin")
        if not isinstance(bobbin,dict) or set(bobbin) != {"bobbin_id","context_digest"} or (
            not isinstance(bobbin.get("context_digest"),str) or not bobbin["context_digest"]):
            raise HTTPException(status_code=422, detail="Contexto de bobina inválido")
        try: bobbin_id = str(uuid.UUID(bobbin["bobbin_id"]))
        except (TypeError,ValueError,AttributeError) as exc:
            raise HTTPException(status_code=422, detail="Bobina inválida") from exc
    elif "bobbin" in value:
        raise HTTPException(status_code=422, detail="Bobina no aplicable")
    raw = _canonical(value)
    if hashlib.sha256(raw).hexdigest() != body.payload_sha256:
        raise HTTPException(status_code=409, detail="Integridad de la captura no verificada")
    return value["payload"],bobbin_id


def _persisted(connection, capture_id: str, author: str):
    return connection.execute(
        """SELECT c.id, c.created_by, f.code, fv.version_number, d.external_key,
                  m.code, c.bobbin_id, c.status
           FROM vinto_txn.capture c
           JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
           JOIN vinto_config.form f ON f.id=fv.form_id
           JOIN vinto_master.device d ON d.id=c.device_id
           JOIN vinto_master.machine m ON m.id=c.machine_id
           WHERE c.id=%s AND c.created_by=%s AND fv.area='quality'
             AND c.status IN ('submitted','closed')""",
        (capture_id, author)).fetchone()


@router.post("")
def send_offline_capture(
    body: OfflineQualityCaptureIn,
    response: Response,
    user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)),
    connection=Depends(get_connection),
):
    response.headers["Cache-Control"] = "no-store"
    _enabled()
    values,bobbin_id = _validate_capture(body,user)
    op = Operation(FORM_OPERATION[body.form_code])
    # This is an operational write. Never reuse observe/off mode even when
    # the online legacy endpoint is configured to be permissive.
    decision = authorize(connection, user, op, body.machine_code, body.form_code, lock=False)
    if not decision.allowed or decision.effective_version != body.form_version:
        raise HTTPException(status_code=403, detail="Permiso o versión de formulario no vigente")
    request_id = str(uuid.uuid4())
    gate = gate_for(user, "enforce", request_id, op)
    if bobbin_id is None:
        result = machine_capture_service.submit_machine_capture(
            connection, actor_id=user.user_id, machine_code=body.machine_code,
            capture_id=str(body.capture_id), form_code=body.form_code,
            device_key=str(body.device_key), values=values, request_id=request_id,
            sectors=user.sectors, gate=gate,
        )
    else:
        # The existing service rechecks authoritative bobbin context and
        # applies the same server validations as the online form.
        result = capture_service.submit_quality_capture(
            connection, actor_id=user.user_id, bobbin_id=bobbin_id,
            capture_id=str(body.capture_id), form_code=body.form_code,
            device_key=str(body.device_key), values=values, request_id=request_id,
            sectors=user.sectors, gate=gate,
        )
    row = _persisted(connection, str(body.capture_id), str(user.user_id))
    if not row or row[2] != body.form_code or row[3] != body.form_version or (
        str(row[4]) != str(body.device_key) or row[5] != body.machine_code) or (
        str(row[6]) if row[6] else None) != bobbin_id:
        raise HTTPException(status_code=409, detail="Captura operativa no verificable")
    response.status_code = 201 if result.created else 200
    return {
        "capture_id":str(body.capture_id), "payload_sha256":body.payload_sha256,
        "server_id":str(body.capture_id), "outcome":"created" if result.created else "duplicate",
        "technical_acceptance":True, "operational_registered":True,
        "operational_capture_id":str(body.capture_id), "warnings":[],
    }


@router.get("/{capture_id}")
def reconcile_offline_capture(
    capture_id: uuid.UUID,
    response: Response,
    user: AuthenticatedUser = Depends(require_permission(QUALITY_CAPTURE)),
    connection=Depends(get_connection),
):
    response.headers["Cache-Control"] = "no-store"
    _enabled()
    row = _persisted(connection, str(capture_id), str(user.user_id))
    if not row:
        return Response(content='{"found":false}',status_code=404,media_type="application/json",
                        headers={"Cache-Control":"no-store"})
    operation = FORM_OPERATION.get(row[2])
    if not operation: raise HTTPException(status_code=404, detail="Captura no encontrada")
    decision=authorize(connection,user,Operation(operation),row[5],row[2],lock=False)
    if not decision.allowed:
        raise HTTPException(status_code=403,detail="Permiso insuficiente")
    return {
        "found":True,"capture_id":str(capture_id),"server_id":str(capture_id),
        "outcome":"accepted","industrial_approval":False,"warnings":[],
        "operational_registered":True,"operational_capture_id":str(capture_id),
    }
