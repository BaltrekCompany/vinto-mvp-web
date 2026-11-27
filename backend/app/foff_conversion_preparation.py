"""FOFF-02B.4 — signed *preparation* metadata, never CAPTURE authority.

Separate domain/shape/key from the Quality CAPTURE envelope. A receiver MUST
reject this kind. JSON is canonicalized with the existing shared encoder.
"""
import hashlib
import re
import uuid
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from app.quality.offline_capture_scope import _b64, _canonical

DOMAIN = b"VINTO-FOFF-CONVERSION-PREPARATION-V1\x00"
CONVERSION_CODES = frozenset({"VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13", "VINTO-P1-16"})


def sign_conversion_preparation(*, seed_hex: str, user_id: str, device_key: str,
                                context: dict, now: datetime | None = None) -> dict:
    if not isinstance(seed_hex, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", seed_hex):
        raise ValueError("invalid signing seed")
    if not isinstance(context, dict) or set(context) != {
        "assignment_id", "work_order_id", "line_id", "machine_code",
        "form_code", "form_version", "article_code", "shift_code",
        "operating_date", "reference_sha256", "context_digest",
    }:
        raise ValueError("invalid preparation context")
    if context["form_code"] not in CONVERSION_CODES or not isinstance(context["form_version"], int) or (
        isinstance(context["form_version"], bool) or context["form_version"] < 1
    ):
        raise ValueError("invalid conversion form")
    if not isinstance(context["machine_code"], str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,48}", context["machine_code"]):
        raise ValueError("invalid machine")
    for key in ("assignment_id", "work_order_id", "line_id"):
        uuid.UUID(str(context[key]))
    for key in ("article_code", "shift_code", "operating_date"):
        if not isinstance(context[key], str) or not context[key]:
            raise ValueError("invalid context field")
    if not re.fullmatch(r"[0-9a-f]{64}", str(context["reference_sha256"])):
        raise ValueError("invalid reference digest")
    if not re.fullmatch(r"[0-9a-f]{64}", str(context["context_digest"])):
        raise ValueError("invalid context digest")
    user_id = str(uuid.UUID(user_id))
    device_key = str(uuid.UUID(device_key))
    issued = (now or datetime.now(timezone.utc))
    if issued.tzinfo is None:
        raise ValueError("aware clock required")
    issued = issued.astimezone(timezone.utc).replace(microsecond=0)
    payload = {
        "schema": "vinto.foff.conversion_preparation.v1",
        "kind": "preparation_only",
        "issuer": "vinto-backend",
        "audience": "vinto-foff-conversion-preparation",
        "snapshot_id": str(uuid.uuid4()),
        "subject_user_id": user_id,
        "device_key": device_key,
        "issued_at": issued.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "expires_at": (issued + timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "context": context,
    }
    private = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed_hex))
    public = private.public_key().public_bytes(encoding=serialization.Encoding.Raw,
                                               format=serialization.PublicFormat.Raw)
    return {
        "algorithm": "Ed25519",
        "key_id": "ed25519-" + hashlib.sha256(public).digest()[:10].hex(),
        "public_key_b64url": _b64(public),
        "payload": payload,
        "signature_b64url": _b64(private.sign(DOMAIN + _canonical(payload))),
    }
