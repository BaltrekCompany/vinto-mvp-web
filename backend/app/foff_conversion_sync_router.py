"""FOFF-03 Conversion offline intake and reconciliation.

OFF by default. Only an authenticated, currently authorized original author
may submit. The signed preparation is NOT capture authority. Normal production
service rechecks all current grants and operational context with row locks.
Stale/expired requests receive immutable technical review receipts (202), not
fake operational confirmations.
"""
import hashlib
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, UUID4

from app import capture_service
from app.auth.dependencies import require_permission
from app.auth.permissions import PRODUCTION_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.capture_gate import gate_for
from app.authz.engine import authorize
from app.authz.policies import Operation
from app.capture_errors import AssignmentNotActiveError, AssignmentStaleError, LineNotInProductionError
from app.config import settings
from app.database import get_connection
from app.foff_conversion_preparation import CONVERSION_CODES, DOMAIN
from app.quality.offline_capture_scope import _canonical

router = APIRouter(prefix="/api/offline/production/conversion/captures",tags=["Conversión Offline"])
SHA=re.compile(r"^[a-f0-9]{64}$")
UUID4_PATTERN=re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$",re.I)


class OfflineConversionIn(BaseModel):
    capture_id: UUID4
    author_user_id: uuid.UUID
    device_key: UUID4
    form_code: str
    form_version: int = Field(gt=0)
    assignment_id: uuid.UUID
    machine_code: str
    scope_snapshot_id: UUID4
    payload_sha256: str
    values: dict[str, Any]
    preparation: dict[str, Any]
    reference_package: dict[str, Any]
    client_captured_at: datetime | None = None


def _enabled():
    if not settings.offline_conversion_capture_enabled:
        raise HTTPException(503,"Conversión offline no habilitada")


def _seed():
    secret=settings.offline_conversion_preparation_signing_seed_hex
    if not secret or not re.fullmatch("[0-9a-fA-F]{64}",secret.get_secret_value()):
        raise HTTPException(503,"Firma de preparación no disponible")
    return secret.get_secret_value()


def _verified_preparation(body:OfflineConversionIn, user:AuthenticatedUser)->tuple[dict,bool]:
    import base64
    input=body.preparation
    if set(input)!={"algorithm","key_id","public_key_b64url","payload","signature_b64url"} or input.get("algorithm")!="Ed25519":
        raise HTTPException(422,"Sobre de preparación inválido")
    payload=input.get("payload")
    if not isinstance(payload,dict) or set(payload)!={
        "schema","kind","issuer","audience","snapshot_id","subject_user_id",
        "device_key","issued_at","expires_at","context",
    }:
        raise HTTPException(422,"Preparación inválida")
    if (payload["schema"]!="vinto.foff.conversion_preparation.v1" or
        payload["kind"]!="preparation_only" or payload["issuer"]!="vinto-backend" or
        payload["audience"]!="vinto-foff-conversion-preparation" or
        payload["subject_user_id"]!=str(user.user_id) or
        payload["subject_user_id"]!=str(body.author_user_id) or
        payload["device_key"]!=str(body.device_key) or
        payload["snapshot_id"]!=str(body.scope_snapshot_id)):
        raise HTTPException(403,"Preparación de otro autor, dispositivo o contexto")
    context=payload["context"]
    if not isinstance(context,dict) or set(context)!={
        "assignment_id","work_order_id","line_id","machine_code","form_code",
        "form_version","article_code","shift_code","operating_date",
        "reference_sha256","context_digest",
    }:
        raise HTTPException(422,"Contexto de preparación inválido")
    if (context["assignment_id"]!=str(body.assignment_id) or
        context["machine_code"]!=body.machine_code or
        context["form_code"]!=body.form_code or
        context["form_version"]!=body.form_version or
        body.form_code not in CONVERSION_CODES):
        raise HTTPException(409,"Contexto de Conversión no coincide")
    expected_hash=context.get("context_digest")
    raw_context={k:v for k,v in context.items() if k!="context_digest"}
    if not isinstance(expected_hash,str) or not SHA.fullmatch(expected_hash) or (
        hashlib.sha256(_canonical(raw_context)).hexdigest()!=expected_hash):
        raise HTTPException(409,"Contexto de Conversión alterado")
    reference_hash=context.get("reference_sha256")
    if not isinstance(reference_hash,str) or not SHA.fullmatch(reference_hash) or (
        hashlib.sha256(_canonical(body.reference_package)).hexdigest()!=reference_hash):
        raise HTTPException(409,"Referencias de Conversión alteradas")
    refs=body.reference_package
    if (refs.get("schema")!="vinto.foff.conversion.references.v1" or
        refs.get("machine_code")!=body.machine_code or
        refs.get("form_code")!=body.form_code or
        refs.get("form_version")!=body.form_version or
        refs.get("article_code")!=context["article_code"]):
        raise HTTPException(409,"Paquete de referencias incorrecto")
    seed=_seed()
    private=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))
    public=private.public_key()
    from cryptography.hazmat.primitives import serialization
    from app.quality.offline_capture_scope import _b64
    raw_public=public.public_bytes(encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw)
    canonical_pin=_b64(raw_public)
    expected_id="ed25519-"+hashlib.sha256(raw_public).digest()[:10].hex()
    if input["key_id"]!=expected_id or input["public_key_b64url"]!=canonical_pin:
        raise HTTPException(403,"Firma no confiable")
    sig=input["signature_b64url"]
    if not isinstance(sig,str) or not re.fullmatch("[A-Za-z0-9_-]+",sig):
        raise HTTPException(422,"Firma inválida")
    try:
        sig_raw=base64.urlsafe_b64decode(sig+"="*((-len(sig))%4))
        if len(sig_raw)!=64 or _b64(sig_raw)!=sig: raise ValueError()
        public.verify(sig_raw,DOMAIN+_canonical(payload))
    except (ValueError,TypeError) as exc:
        raise HTTPException(403,"Firma de preparación inválida") from exc
    except Exception as exc:
        raise HTTPException(403,"Firma de preparación inválida") from exc
    try:
        issued=datetime.strptime(payload["issued_at"],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        expires=datetime.strptime(payload["expires_at"],"%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        if not 0<(expires-issued).total_seconds()<=12*3600:
            raise ValueError("invalid expiry")
    except (ValueError,TypeError) as exc:
        raise HTTPException(422,"Vigencia de preparación inválida") from exc
    # Local timestamp has no authority. Expired envelope => durable review only.
    return context, datetime.now(timezone.utc)>=expires


def _stored(connection,capture_id,author):
    return connection.execute(
        """SELECT c.id,c.created_by,f.code,fv.version_number,d.external_key,m.code,c.assignment_id,c.status
           FROM vinto_txn.capture c JOIN vinto_config.form_version fv ON fv.id=c.form_version_id
           JOIN vinto_config.form f ON f.id=fv.form_id
           JOIN vinto_master.device d ON d.id=c.device_id
           JOIN vinto_master.machine m ON m.id=c.machine_id
           WHERE c.id=%s AND c.created_by=%s AND fv.area='production'
             AND c.status IN ('submitted','closed')""",
        (capture_id,author),
    ).fetchone()


def _review(connection,body:OfflineConversionIn,user:AuthenticatedUser,context,reason):
    with connection.transaction():
        capture_service._context(connection,user.user_id,f"foff-review:{uuid.uuid4()}")
        connection.execute(
            """INSERT INTO vinto_txn.offline_conversion_review
              (capture_id,author_user_id,device_key,assignment_id,form_code,form_version,
               machine_code,payload_sha256,request_payload,original_context,reason,client_captured_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,%s,%s)
               ON CONFLICT (capture_id) DO NOTHING""",
            (body.capture_id,user.user_id,body.device_key,body.assignment_id,
             body.form_code,body.form_version,body.machine_code,body.payload_sha256,
             __import__("json").dumps(body.values,ensure_ascii=False),
             __import__("json").dumps(context,ensure_ascii=False),reason,body.client_captured_at),
        )
        row=connection.execute(
            """SELECT author_user_id,device_key,assignment_id,form_code,form_version,
                      machine_code,payload_sha256,reason,original_context
               FROM vinto_txn.offline_conversion_review WHERE capture_id=%s""",
            (body.capture_id,),
        ).fetchone()
        if not row or row[:7]!=(user.user_id,body.device_key,body.assignment_id,
                                 body.form_code,body.form_version,body.machine_code,body.payload_sha256):
            raise HTTPException(409,"Conflicto de idempotencia en revisión")
        if row[8] != context:
            raise HTTPException(409,"Contexto de revisión ya registrado")
        return row[7]


@router.post("")
def receive_conversion_capture(
    body:OfflineConversionIn,response:Response,
    user:AuthenticatedUser=Depends(require_permission(PRODUCTION_CAPTURE)),
    connection=Depends(get_connection),
):
    response.headers["Cache-Control"]="no-store"
    _enabled()
    if str(body.author_user_id)!=str(user.user_id) or not UUID4_PATTERN.fullmatch(str(body.device_key)):
        raise HTTPException(403,"Autor o dispositivo no autorizado")
    if body.form_code not in CONVERSION_CODES or not SHA.fullmatch(body.payload_sha256):
        raise HTTPException(422,"Formulario o hash inválido")
    try:
        digest=hashlib.sha256(_canonical(body.values)).hexdigest()
    except (TypeError,ValueError) as exc:
        raise HTTPException(422,"Valores no canónicos") from exc
    if digest!=body.payload_sha256:
        raise HTTPException(409,"Integridad de captura no verificada")
    context,expired=_verified_preparation(body,user)
    decision=authorize(connection,user,Operation.PRODUCTION_CAPTURE,
                       body.machine_code,body.form_code,lock=False)
    if not decision.allowed or decision.effective_version!=body.form_version:
        raise HTTPException(403,"Permiso o versión no vigente")
    existing=_stored(connection,body.capture_id,user.user_id)
    if existing:
        if (existing[2]!=body.form_code or existing[3]!=body.form_version or
            str(existing[4])!=str(body.device_key) or existing[5]!=body.machine_code or
            str(existing[6])!=str(body.assignment_id)):
            raise HTTPException(409,"Captura persistida no coincide")
        response.status_code=200
        return {"capture_id":str(body.capture_id),"outcome":"duplicate",
                "operational_registered":True,"technical_acceptance":True}
    # Once a request has a durable technical receipt it is never silently
    # promoted to a business capture by a later retry with the same capture_id.
    pending=connection.execute(
        "SELECT reason FROM vinto_txn.offline_conversion_review WHERE capture_id=%s",
        (body.capture_id,),
    ).fetchone()
    if pending:
        reason=_review(connection,body,user,context,pending[0])
        response.status_code=202
        return {"capture_id":str(body.capture_id),"outcome":"review",
                "reason":reason,"operational_registered":False,"technical_acceptance":True}
    if expired:
        reason=_review(connection,body,user,context,"preparation_expired")
        response.status_code=202
        return {"capture_id":str(body.capture_id),"outcome":"review",
                "reason":reason,"operational_registered":False,"technical_acceptance":True}
    request_id=str(uuid.uuid4())
    gate=gate_for(user,"enforce",request_id,Operation.PRODUCTION_CAPTURE)
    try:
        result=capture_service.submit_production_capture(
            connection,actor_id=user.user_id,capture_id=body.capture_id,
            form_code=body.form_code,assignment_id=body.assignment_id,
            device_key=str(body.device_key),values=body.values,request_id=request_id,
            sectors=user.sectors,gate=gate,
        )
    except (AssignmentStaleError,AssignmentNotActiveError,LineNotInProductionError) as exc:
        reasons={AssignmentStaleError:"assignment_stale",
                 AssignmentNotActiveError:"assignment_not_active",
                 LineNotInProductionError:"line_not_in_production"}
        reason=_review(connection,body,user,context,reasons[type(exc)])
        response.status_code=202
        return {"capture_id":str(body.capture_id),"outcome":"review","reason":reason,
                "operational_registered":False,"technical_acceptance":True}
    row=_stored(connection,body.capture_id,user.user_id)
    if not row or row[2]!=body.form_code or row[3]!=body.form_version or (
        str(row[4])!=str(body.device_key) or row[5]!=body.machine_code or
        str(row[6])!=str(body.assignment_id)):
        raise HTTPException(409,"Registro operativo no verificable")
    response.status_code=201 if result.created else 200
    return {"capture_id":str(body.capture_id),"outcome":"created" if result.created else "duplicate",
            "operational_registered":True,"technical_acceptance":True,
            "operational_capture_id":str(body.capture_id)}


@router.get("/{capture_id}")
def reconcile_conversion_capture(
    capture_id:uuid.UUID,response:Response,
    user:AuthenticatedUser=Depends(require_permission(PRODUCTION_CAPTURE)),
    connection=Depends(get_connection),
):
    response.headers["Cache-Control"]="no-store"
    _enabled()
    row=_stored(connection,capture_id,user.user_id)
    if row:
        decision=authorize(connection,user,Operation.PRODUCTION_CAPTURE,row[5],row[2],lock=False)
        if not decision.allowed: raise HTTPException(403,"Permiso insuficiente")
        return {"found":True,"outcome":"accepted","operational_registered":True,
                "capture_id":str(capture_id),"operational_capture_id":str(capture_id)}
    row=connection.execute(
        """SELECT author_user_id,machine_code,form_code,reason FROM vinto_txn.offline_conversion_review
           WHERE capture_id=%s AND author_user_id=%s""",(capture_id,user.user_id),
    ).fetchone()
    if not row:
        return Response(content='{"found":false}',status_code=404,
                        media_type="application/json",headers={"Cache-Control":"no-store"})
    decision=authorize(connection,user,Operation.PRODUCTION_CAPTURE,row[1],row[2],lock=False)
    if not decision.allowed: raise HTTPException(403,"Permiso insuficiente")
    return {"found":True,"outcome":"review","reason":row[3],
            "operational_registered":False,"capture_id":str(capture_id)}
