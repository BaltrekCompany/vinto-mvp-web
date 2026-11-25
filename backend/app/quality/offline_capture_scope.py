"""Signed, short-lived Quality CAPTURE authority for previously enrolled devices.

The envelope binds the original user, device, active grant, machine and
published version. Signing is server-only; issuance never authorizes upload:
the operational receiver MUST re-check revocations and context atomically.
This module creates no grants, enrolments or production writes.
"""
import base64
import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DOMAIN = b"VINTO-OFFLINE-CAPTURE-SCOPE-V1\x00"
UUID4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$", re.I)
MACHINE = re.compile(r"^[A-Za-z0-9_.-]{1,48}$")
FORM_OPERATION = {
    **{f"VINTO-P1-{n}": "quality_machine_capture" for n in (18,22,26,27)},
    **{f"VINTO-P1-{n}": "quality_bobbin_capture" for n in (19,20,21,24,25,28)},
}


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _canonical(value) -> bytes:
    # Matches canonicalOfflineJson() in the web verifier: sorted keys, UTF-8,
    # compact JSON, no floating point or NaN, Unicode preserved.
    if type(value) is dict:
        return b"{" + b",".join(
            json.dumps(k, ensure_ascii=False, separators=(",", ":")).encode() +
            b":" + _canonical(value[k]) for k in sorted(value)
        ) + b"}"
    if type(value) is list:
        return b"[" + b",".join(map(_canonical, value)) + b"]"
    if value is None or type(value) in (str,bool) or (type(value) is int and abs(value) <= 2**53-1):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode()
    raise ValueError("invalid canonical scope value")


def sign_quality_capture_scope(*, signing_seed_hex: str, subject_user_id: str,
                               device_key: str, form_scopes: list[dict],
                               now: datetime | None = None, snapshot_id: str | None = None) -> dict:
    if not isinstance(signing_seed_hex,str) or not re.fullmatch(r"[0-9a-fA-F]{64}", signing_seed_hex):
        raise ValueError("invalid offline signing configuration")
    try:
        subject_user_id = str(uuid.UUID(subject_user_id)).lower()
        device_key = str(uuid.UUID(device_key)).lower()
    except (TypeError,ValueError,AttributeError) as exc:
        raise ValueError("invalid offline identity") from exc
    if not UUID4.fullmatch(device_key):
        raise ValueError("invalid offline device identifier")
    if not 1 <= len(form_scopes) <= 200:
        raise ValueError("invalid offline scope count")
    seen = set()
    clean = []
    for entry in form_scopes:
        if type(entry) is not dict or set(entry) != {"machine_code","form_code","form_version","operation","grant_id"}:
            raise ValueError("invalid offline form scope")
        machine, form, version = entry["machine_code"], entry["form_code"], entry["form_version"]
        if not isinstance(machine,str) or not MACHINE.fullmatch(machine) or form not in FORM_OPERATION or (
            type(version) is not int or version < 1 or version > 2**53-1) or (
            entry["operation"] != FORM_OPERATION[form]):
            raise ValueError("invalid offline form scope")
        try: grant = str(uuid.UUID(str(entry["grant_id"]))).lower()
        except (TypeError,ValueError,AttributeError) as exc: raise ValueError("invalid grant") from exc
        identity = (machine,form,version,entry["operation"])
        if identity in seen: raise ValueError("duplicate offline form scope")
        seen.add(identity)
        clean.append({**entry,"grant_id":grant})
    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None: raise ValueError("timezone required")
    instant = instant.astimezone(timezone.utc).replace(microsecond=0)
    snapshot = snapshot_id or str(uuid.uuid4())
    if not UUID4.fullmatch(snapshot): raise ValueError("invalid snapshot id")
    payload = {
        "schema":"vinto.offline.capture_scope.v1",
        "issuer":"vinto-backend",
        "audience":"vinto-offline-operational-capture",
        "kind":"capture_authority",
        "snapshot_id":snapshot,
        "subject_user_id":subject_user_id,
        "device_key":device_key,
        "issued_at":instant.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at":(instant+timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "form_scopes":clean,
    }
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(signing_seed_hex))
    public = private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return {
        "algorithm":"Ed25519",
        "key_id":"ed25519-"+hashlib.sha256(public).digest()[:10].hex(),
        "public_key_b64url":_b64(public),
        "payload":payload,
        "signature_b64url":_b64(private.sign(DOMAIN+_canonical(payload))),
    }
