"""FOFF-03 Conversion CAPTURE authority: separate key, domain and schema.

This authorizes OFFLINE EDITOR readiness only for one assigned form/device/author.
The server reauthorizes in the same business transaction on synchronisation.
"""
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.quality.offline_capture_scope import _b64, _canonical

DOMAIN=b"VINTO-FOFF-CONVERSION-CAPTURE-AUTHORITY-V1\x00"
SCHEMA="vinto.foff.conversion_capture.v1"
AUDIENCE="vinto-foff-conversion-capture"


def _private(seed_hex):
    if not isinstance(seed_hex,str) or not re.fullmatch(r"[0-9a-fA-F]{64}",seed_hex):
        raise ValueError("invalid capture signing seed")
    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))


def public_pin(seed_hex):
    key=_private(seed_hex)
    raw=key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,format=serialization.PublicFormat.Raw,
    )
    return {
        "algorithm":"Ed25519",
        "key_id":"ed25519-"+hashlib.sha256(raw).digest()[:10].hex(),
        "public_key_b64url":_b64(raw),
    }


def sign_conversion_capture_authority(
    *,seed_hex,user_id,device_key,snapshot_id,assignment_id,machine_code,
    form_code,form_version,grant_id,reference_sha256,now=None,
):
    if not all(isinstance(v,str) for v in (machine_code,form_code,reference_sha256)) or (
        not re.fullmatch(r"[a-f0-9]{64}",reference_sha256)
    ):
        raise ValueError("invalid capture authority target")
    from app.foff_conversion_preparation import CONVERSION_CODES
    if form_code not in CONVERSION_CODES or not isinstance(form_version,int) or (
        isinstance(form_version,bool) or form_version<1
    ):
        raise ValueError("unsupported capture form")
    p={
        "schema":SCHEMA,"issuer":"vinto-backend",
        "audience":AUDIENCE,"kind":"capture_authority",
        "snapshot_id":str(uuid.UUID(str(snapshot_id))),
        "subject_user_id":str(uuid.UUID(str(user_id))),
        "device_key":str(uuid.UUID(str(device_key))),
        "assignment_id":str(uuid.UUID(str(assignment_id))),
        "machine_code":machine_code,
        "form_code":form_code,
        "form_version":form_version,
        "grant_id":str(uuid.UUID(str(grant_id))),
        "reference_sha256":reference_sha256,
    }
    issued=(now or datetime.now(timezone.utc))
    if issued.tzinfo is None:raise ValueError("aware clock required")
    issued=issued.astimezone(timezone.utc).replace(microsecond=0)
    p["issued_at"]=issued.strftime("%Y-%m-%dT%H:%M:%SZ")
    p["expires_at"]=(issued+timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ")
    key=_private(seed_hex)
    pin=public_pin(seed_hex)
    return {**pin,"payload":p,"signature_b64url":_b64(key.sign(DOMAIN+_canonical(p)))}
