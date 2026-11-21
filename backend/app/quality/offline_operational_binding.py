"""OFF-04.8P: explicit, opt-in binding of registered CAPTURE authority to promoter.

This is NOT an endpoint or application mount. No new grants or authorization matrix:
the issuer derives pairs from MF-13 and the online Quality services still apply
MF-13 effective authorization under lock at the time of operational registration.
"""
from __future__ import annotations

from app.offline_scope.signing import decode_b64
from app.quality.offline_capture_authority import verify_registered_capture_scope
from app.quality.offline_operational import QualityOperationalPromoter


def registered_scope_promoter(*, trusted_public_key_b64url: str) -> QualityOperationalPromoter:
    """Bind the authoritative DB verifier, with a required pinned Ed25519 key.

    Only the external, separately authorized composition root can opt into this
    factory. The receipt transaction's psycopg connection is passed to the
    verifier; no preflight result or client-supplied envelope grants authority.
    """
    if not isinstance(trusted_public_key_b64url, str) or not trusted_public_key_b64url:
        raise ValueError("trusted_capture_signer_required")
    try:
        decode_b64(trusted_public_key_b64url, 32)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid_trusted_capture_signer") from exc

    def verify(principal, capture, connection) -> bool:
        return verify_registered_capture_scope(
            connection,
            principal=principal,
            capture=capture,
            trusted_public_key_b64url=trusted_public_key_b64url,
        ) is True

    return QualityOperationalPromoter(verify_capture_scope=verify)
