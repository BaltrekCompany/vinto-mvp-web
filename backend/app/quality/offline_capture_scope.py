"""OFF-04.8C: closed capture-capable scope verifier (NOT an issuer, NOT mounted).

The existing offline scope has a DIFFERENT domain and "readiness only" audience:
it must NEVER authorize industrial writes. This verifier accepts only independently
signed operational envelopes from a future, explicitly activated server-side issuer.
The current authorization and user session are re-checked separately by the online
Quality service inside the same database transaction.

No route issues these tokens and there is no production activation in this increment.
"""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone, timedelta
from typing import Any, Callable
from uuid import UUID

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.offline_scope.signing import canonical_payload, decode_b64

DOMAIN = b"VINTO-OFFLINE-CAPTURE-SCOPE-V1\x00"
SCHEMA = "vinto.offline.capture_scope.v1"
AUDIENCE = "vinto-offline-operational-capture"
KIND = "capture_authority"
EXPECTED_FIELDS = frozenset({
    "schema", "issuer", "audience", "kind", "snapshot_id", "subject_user_id",
    "device_key", "issued_at", "expires_at", "form_scopes",
})
ENTRY_FIELDS = frozenset({"machine_code", "form_code", "form_version", "operation", "grant_id"})
MAX_ENTRIES = 200


def _time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.endswith("Z"):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def verified_capture_scope(
    envelope: Any, principal: Any, capture: Any, *, trusted_public_key_b64url: str,
    now: datetime | None = None, snapshot_active: Callable[[UUID, UUID], bool] | None = None,
) -> bool:
    """Fail-closed verification of independently signed capture scope.

    snapshot_active is an obligatory authoritative server callback checking that
    this snapshot was actually issued and has not been revoked. Offline possession
    of a signature by itself never grants operational authority.
    """
    if not callable(snapshot_active) or not isinstance(envelope, dict):
        return False
    if set(envelope) != {"algorithm", "key_id", "public_key_b64url", "payload", "signature_b64url"}:
        return False
    payload = envelope.get("payload")
    if not isinstance(payload, dict) or set(payload) != EXPECTED_FIELDS:
        return False
    if payload.get("schema") != SCHEMA or payload.get("audience") != AUDIENCE or payload.get("kind") != KIND or payload.get("issuer") != "vinto-backend":
        return False
    try:
        pub = decode_b64(trusted_public_key_b64url, 32)
        if envelope["algorithm"] != "Ed25519" or envelope["public_key_b64url"] != trusted_public_key_b64url:
            return False
        if envelope["key_id"] != "ed25519-" + hashlib.sha256(pub).hexdigest()[:20]:
            return False
        signature = decode_b64(envelope["signature_b64url"], 64)
        Ed25519PublicKey.from_public_bytes(pub).verify(signature, DOMAIN + canonical_payload(payload))
        snapshot = UUID(payload["snapshot_id"])
        user_id = UUID(payload["subject_user_id"])
        device = UUID(payload["device_key"])
        if snapshot.version != 4 or device.version != 4:
            return False
        if user_id != principal.user_id or user_id != capture.author_user_id or device != capture.device_key or snapshot != capture.scope_snapshot_id:
            return False
        issued, expires = _time(payload["issued_at"]), _time(payload["expires_at"])
        clock = now or datetime.now(timezone.utc)
        if issued is None or expires is None or clock.tzinfo is None:
            return False
        # Explicitly capped, bounded validity with no implicit clock-skew privilege.
        if not issued <= clock < expires or expires - issued > timedelta(hours=24):
            return False
        forms = payload["form_scopes"]
        if not isinstance(forms, list) or not 1 <= len(forms) <= MAX_ENTRIES:
            return False
        matches = 0
        for entry in forms:
            if not isinstance(entry, dict) or set(entry) != ENTRY_FIELDS:
                return False
            if not isinstance(entry["form_version"], int) or isinstance(entry["form_version"], bool) or entry["form_version"] < 1:
                return False
            if not isinstance(entry["machine_code"], str) or not isinstance(entry["form_code"], str) or not isinstance(entry["operation"], str):
                return False
            UUID(entry["grant_id"])
            if (entry["machine_code"] == capture.machine_code and entry["form_code"] == capture.form_code
                    and entry["form_version"] == capture.form_version and entry["operation"] in
                    ("quality_machine_capture", "quality_bobbin_capture")):
                # Form kind must agree with the authoritative server policy.
                from app.offline_quality.registry import spec_for
                spec = spec_for(capture.form_code)
                if spec is not None and entry["operation"] == spec.operation.value:
                    matches += 1
        if matches != 1:
            return False
        return snapshot_active(snapshot, principal.user_id) is True
    except (KeyError, ValueError, TypeError, InvalidSignature):
        return False
