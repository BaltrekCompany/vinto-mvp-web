"""OFF-04.8D: standalone capture-authority issuer + revocation registry.

NOT imported by app.main, NOT mounted, NOT deployed. Requires a separately
approved migration and operational flag. Unlike readiness scopes, this module
signs only Quality pairs approved by the effective online authz engine.

The original user must still be online/authenticated at upload, and current
effective grants are rechecked by the online capture service before writing.
"""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone

from app.auth.permissions import QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.engine import authorize
from app.authz.errors import AuthorizationUnavailable
from app.offline_quality.registry import BATCH_FORMS, spec_for
from app.offline_scope.signing import SigningKey, canonical_payload, encode_b64
from app.quality.offline_capture_scope import AUDIENCE, DOMAIN, KIND, SCHEMA, verified_capture_scope

MAX_SCOPE_PAIRS = 100
LIFETIME = timedelta(hours=24)


class CaptureScopeDenied(Exception):
    pass


def _utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _signed(payload: dict, signer: SigningKey) -> dict:
    """Independent capture domain. Readiness signatures can never verify here."""
    return {
        "algorithm": "Ed25519", "key_id": signer.key_id, "public_key_b64url": signer.public_b64url,
        "payload": payload,
        "signature_b64url": encode_b64(signer.private.sign(DOMAIN + canonical_payload(payload))),
    }


def issue_capture_scope(connection, principal: AuthenticatedUser, *, device_key: uuid.UUID,
                        machine_codes: list[str], signer: SigningKey) -> dict:
    """Atomic issue of signed envelope and snapshot row; no endpoint calls it."""
    if not isinstance(principal, AuthenticatedUser) or principal.must_change or not principal.can(QUALITY_CAPTURE):
        raise CaptureScopeDenied()
    if not isinstance(device_key, uuid.UUID) or device_key.version != 4:
        raise CaptureScopeDenied()
    if not machine_codes or len(machine_codes) > 25 or len(set(machine_codes)) != len(machine_codes):
        raise CaptureScopeDenied()
    if not all(isinstance(code, str) and code and len(code) <= 48 for code in machine_codes):
        raise CaptureScopeDenied()

    with connection.transaction():
        candidates = connection.execute(
            """SELECT m.code, f.code FROM vinto_master.user_machine_form_grant g
               JOIN vinto_master.machine m ON m.id=g.machine_id
               JOIN vinto_config.form f ON f.id=g.form_id
               WHERE g.user_id=%s AND g.revoked_at IS NULL
                 AND m.code=ANY(%s) AND f.code=ANY(%s)
               ORDER BY m.code, f.code LIMIT %s""",
            (principal.user_id, machine_codes, list(BATCH_FORMS), MAX_SCOPE_PAIRS + 1),
        ).fetchall()
        if len(candidates) > MAX_SCOPE_PAIRS:
            raise CaptureScopeDenied()
        pairs = []
        for machine_code, form_code in candidates:
            spec = spec_for(form_code)
            if spec is None:
                continue
            # Row-level locks and effective profile/sector checks, not client claims.
            decision = authorize(connection, principal, spec.operation, machine_code, form_code, lock=True)
            if not decision.allowed:
                continue
            if not decision.grant_id or not decision.effective_version or decision.effective_version < 1:
                raise AuthorizationUnavailable("INVALID_CAPTURE_SCOPE_GRANT")
            pairs.append({
                "machine_code": machine_code,
                "form_code": form_code,
                "form_version": decision.effective_version,
                "operation": spec.operation.value,
                "grant_id": str(decision.grant_id),
            })
        if not pairs:
            raise CaptureScopeDenied()

        # Server clock, not device clock, determines the signed issuance window.
        issued = connection.execute("SELECT clock_timestamp()").fetchone()[0].astimezone(timezone.utc)
        expires = issued + LIFETIME
        payload = {
            "schema": SCHEMA, "issuer": "vinto-backend", "audience": AUDIENCE, "kind": KIND,
            "snapshot_id": str(uuid.uuid4()), "subject_user_id": str(principal.user_id),
            "device_key": str(device_key),
            "issued_at": _utc(issued), "expires_at": _utc(expires),
            "form_scopes": pairs,
        }
        envelope = _signed(payload, signer)
        digest = hashlib.sha256(canonical_payload(envelope)).hexdigest()
        from psycopg.types.json import Jsonb
        connection.execute(
            """INSERT INTO vinto_offline.capture_scope_authority
               (snapshot_id,subject_user_id,device_key,payload_sha256,envelope,issued_at,expires_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (uuid.UUID(payload["snapshot_id"]), principal.user_id, device_key, digest,
             Jsonb(envelope), issued, expires),
        )
        return envelope


def revoke_capture_scope(connection, *, snapshot_id: uuid.UUID, subject_user_id: uuid.UUID) -> bool:
    """One-way revocation, same-row lock serializes with in-flight promotion."""
    with connection.transaction():
        n = connection.execute(
            """UPDATE vinto_offline.capture_scope_authority SET revoked_at=clock_timestamp()
               WHERE snapshot_id=%s AND subject_user_id=%s
                 AND revoked_at IS NULL AND expires_at>clock_timestamp()""",
            (snapshot_id, subject_user_id),
        ).rowcount
        return n == 1


def verify_registered_capture_scope(connection, *, principal: AuthenticatedUser,
                                    capture, trusted_public_key_b64url: str) -> bool:
    """Called inside the receipt/operational write transaction.

    Uses a share lock so revocation cannot race between verification and commit.
    An unknown, forged, stale or modified envelope fails closed.
    """
    if capture.scope_snapshot_id is None:
        return False
    row = connection.execute(
        """SELECT envelope,payload_sha256,device_key
           FROM vinto_offline.capture_scope_authority
           WHERE snapshot_id=%s AND subject_user_id=%s
             AND revoked_at IS NULL AND expires_at>clock_timestamp()
           FOR SHARE""",
        (capture.scope_snapshot_id, principal.user_id),
    ).fetchone()
    if row is None or str(row[2]) != str(capture.device_key):
        return False
    envelope, stored_sha, _ = row
    if hashlib.sha256(canonical_payload(envelope)).hexdigest() != stored_sha:
        return False
    # The authoritative database lookup above ensures issuance and revocation
    # state; the verifier checks the independent crypto domain and exact pair.
    return verified_capture_scope(
        envelope, principal, capture, trusted_public_key_b64url=trusted_public_key_b64url,
        snapshot_active=lambda snapshot, user: snapshot == capture.scope_snapshot_id and user == principal.user_id,
    )
