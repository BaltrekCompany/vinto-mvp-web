"""OFF-04.8P: fail-closed, opt-in registered CAPTURE scope pre-authorizer.

A readiness-only package is NEVER a capture permit. This preflight verifies
the server-registered, independently signed CAPTURE scope against PostgreSQL.
It does not grant industrial write privileges: the operational promoter MUST
repeat this check and enforce current MF-13 permissions inside the receipt
transaction. Not mounted in app.main or any production router.
"""
from __future__ import annotations

from typing import Callable

from app.auth.permissions import QUALITY_CAPTURE
from app.offline_capture.service import AuthzDecision
from app.quality.offline_capture_authority import verify_registered_capture_scope
from app.offline_scope.signing import decode_b64


class RegisteredCaptureAuthorizer:
    """Requires a NEW DB connection per request, plus a pinned 32-byte public key."""

    def __init__(self, connect: Callable, *, trusted_public_key_b64url: str):
        if not callable(connect):
            raise TypeError("capture_authorizer_connection_required")
        try:
            decode_b64(trusted_public_key_b64url, 32)
        except (TypeError, ValueError) as exc:
            raise ValueError("invalid_trusted_capture_signer") from exc
        self._connect = connect
        self._trusted = trusted_public_key_b64url

    def authorize(self, principal, capture) -> AuthzDecision:
        if (
            principal.user_id != capture.author_user_id
            or principal.must_change
            or not principal.can(QUALITY_CAPTURE)
            or capture.scope_snapshot_id is None
        ):
            return AuthzDecision(False, "capture_scope_denied")
        # Connectivity or integrity errors propagate: the receiver must fail
        # unavailable, not silently turn a storage failure into an approval.
        with self._connect() as db:
            valid = verify_registered_capture_scope(
                db, principal=principal, capture=capture,
                trusted_public_key_b64url=self._trusted,
            )
        return AuthzDecision(bool(valid), None if valid else "capture_scope_denied")
