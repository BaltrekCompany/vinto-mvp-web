"""OFF-03B.2 scoped offline-readiness issuer; no OT writes and no offline capture.

Only existing effective authorization engine can approve each machine/form.
Use an explicit transaction with FOR SHARE locks through authorize(lock=True):
a concurrent revocation cannot pass between evaluation and signature generation.
"""
from datetime import datetime, timezone
import uuid

from app.auth.permissions import PRODUCTION_CAPTURE, QUALITY_CAPTURE
from app.auth.service import AuthenticatedUser
from app.authz.engine import authorize
from app.authz.errors import AuthorizationUnavailable
from app.authz.policies import POLICIES, Operation
from app.offline_scope.signing import AUDIENCE, ISSUER, SCHEMA, SigningKey, sign_scope

MAX_MACHINE_CODES = 25
MAX_CANDIDATES = 200
ORDERED_OPERATIONS = (
    Operation.PRODUCTION_CAPTURE, Operation.BOBBIN_PRODUCTION,
    Operation.QUALITY_BOBBIN_CAPTURE, Operation.QUALITY_MACHINE_CAPTURE,
)


class OfflineScopeDenied(Exception):
    pass


class OfflineScopeTooLarge(Exception):
    pass


def issue_scope(connection, principal: AuthenticatedUser, *, device_key: uuid.UUID,
                machine_codes: list[str], signer: SigningKey) -> dict:
    if not isinstance(principal, AuthenticatedUser) or principal.must_change:
        raise OfflineScopeDenied()
    if not isinstance(device_key, uuid.UUID) or device_key.version != 4:
        raise OfflineScopeDenied()
    if not machine_codes or len(machine_codes) > MAX_MACHINE_CODES or len(set(machine_codes)) != len(machine_codes):
        raise OfflineScopeDenied()
    if not (principal.can(PRODUCTION_CAPTURE) or principal.can(QUALITY_CAPTURE)):
        raise OfflineScopeDenied()

    pairs = []
    try:
        with connection.transaction():
            # Narrow candidate enumeration to requested machines and ACTIVE grants;
            # never enumerate all catalog forms or trust a client-supplied permission.
            candidates = connection.execute(
                """SELECT m.code, f.code
                   FROM vinto_master.user_machine_form_grant g
                   JOIN vinto_master.machine m ON m.id = g.machine_id
                   JOIN vinto_config.form f ON f.id = g.form_id
                   WHERE g.user_id = %s AND g.revoked_at IS NULL AND m.code = ANY(%s)
                   ORDER BY m.code, f.code LIMIT %s""",
                (principal.user_id, machine_codes, MAX_CANDIDATES + 1),
            ).fetchall()
            if len(candidates) > MAX_CANDIDATES:
                raise OfflineScopeTooLarge()
            for machine_code, form_code in candidates:
                for operation in ORDERED_OPERATIONS:
                    policy = POLICIES[operation]
                    if form_code not in policy.admitted():
                        continue
                    # Re-read current active user, profile, sector, machine, version
                    # and grant in DB. No fallback to claims from the cookie payload.
                    decision = authorize(connection, principal, operation, machine_code, form_code, lock=True)
                    if decision.allowed:
                        if not decision.grant_id or not isinstance(decision.effective_version, int) or decision.effective_version < 1:
                            raise AuthorizationUnavailable("INVALID_EFFECTIVE_GRANT")
                        pairs.append({
                            "machine_code": machine_code,
                            "form_code": form_code,
                            "form_version": decision.effective_version,
                            "grant_id": str(decision.grant_id),
                            "operation": operation.value,
                        })
                    break
            if not pairs:
                raise OfflineScopeDenied()
            # Sign WHILE row locks remain held, not after the transaction commits.
            payload = {
                "schema": SCHEMA,
                "issuer": ISSUER,
                "audience": AUDIENCE,
                "snapshot_id": str(uuid.uuid4()),
                "subject_user_id": str(principal.user_id),
                "device_key": str(device_key),
                "issued_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
                "kind": "scope_readiness_only",
                "captures_enabled": False,
                "form_scopes": pairs,
            }
            return sign_scope(payload, signer=signer)
    except OfflineScopeDenied:
        raise
    except OfflineScopeTooLarge:
        raise
    except AuthorizationUnavailable:
        raise
    # DB errors are handled by global PostgreSQL exception mapping.
