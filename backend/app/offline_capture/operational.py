"""OFF-04.8A — opt-in adapter from a validated offline receipt to the EXISTING online Quality capture services.

This module is deliberately NOT mounted in app.main or the synthetic QA pilot. The caller
must supply a current authenticated principal, a signed-capture authorizer (not a readiness
scope), a central validator and a PostgreSQL receipt transaction. The operational write uses
the SAME PostgreSQL connection and an inner savepoint: receipt + vinto_txn either commit
together or are rolled back together. No release/approval API is invoked.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

import psycopg

from app.auth.permissions import QUALITY_CAPTURE
from app.authz.capture_gate import gate_for
from app.authz.errors import AuthorizationDenied, AuthorizationUnavailable, ResourceNotFound
from app.bobbins.errors import BobbinNotFoundError
from app.capture_errors import (CaptureIdempotencyConflictError, CaptureValidationError,
                                FormNotAvailableError, UnsupportedFormDefinitionError, UnsupportedFormError,
                                DeviceInactiveError, DeviceMachineMismatchError)
from app.offline_capture import contract as C
from app.offline_capture.store import StoreUnavailable
from app.offline_quality import bobbin_context
from app.offline_quality.registry import BOBBIN, MACHINE, spec_for
from app.quality import capture_service as bobbin_service
from app.quality import machine_capture_service as machine_service


class OperationalReview(Exception):
    """Deterministic rejection for this receipt; keep it for review, never create vinto_txn rows."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


@dataclass(frozen=True)
class OperationalRegistration:
    capture_id: uuid.UUID


class QualityOperationalPromoter:
    """Production candidate. No route creates or invokes this adapter yet.

    Its caller MUST verify the signed capture-capable scope and the current authenticated
    operator, independently of this adapter. This adapter *always* re-checks current Quality
    permissions and effective machine/form grants inside the operational write transaction.
    """

    def promote(self, principal: Any, capture: C.CaptureIn, tx: Any) -> OperationalRegistration:
        if principal.user_id != capture.author_user_id or principal.must_change or not principal.can(QUALITY_CAPTURE):
            raise OperationalReview("operational_not_authorized")
        if capture.scope_snapshot_id is None or capture.payload.get("synthetic") is not False:
            raise OperationalReview("operational_scope_required")
        values = capture.payload.get("payload")
        if not isinstance(values, dict):
            raise OperationalReview("operational_payload_shape")
        spec = spec_for(capture.form_code)
        if spec is None or spec.kind not in (MACHINE, BOBBIN):
            raise OperationalReview("operational_unsupported_form")
        connection = getattr(tx, "c", None)
        if not isinstance(connection, psycopg.Connection):
            raise StoreUnavailable("operational_requires_shared_postgres_transaction")

        # Effective authorization cannot be switched off/observed by caller or client.
        request_id = "offline-quality:" + str(uuid.uuid4())
        gate = gate_for(principal, "enforce", request_id, spec.operation)
        try:
            # Savepoint allows a deterministic business refusal to roll back a candidate
            # operational write while the outer receipt remains available for review.
            with connection.transaction():
                if spec.kind == MACHINE:
                    if capture.context_version != str(capture.scope_snapshot_id):
                        raise OperationalReview("operational_context_changed")
                    if "bobbin" in capture.payload:
                        raise OperationalReview("operational_unexpected_bobbin")
                    outcome = machine_service.submit_machine_capture(
                        connection, actor_id=principal.user_id, machine_code=capture.machine_code,
                        capture_id=capture.capture_id, form_code=capture.form_code,
                        device_key=capture.device_key, values=values,
                        request_id=request_id, sectors=principal.sectors, gate=gate,
                    )
                else:
                    ref = capture.payload.get("bobbin")
                    if not isinstance(ref, dict) or set(ref) != {"bobbin_id", "context_digest"}:
                        raise OperationalReview("operational_bobbin_required")
                    context = bobbin_context.load_by_id(connection, ref["bobbin_id"], principal.sectors)
                    if context is None or context["machine_code"] != capture.machine_code:
                        raise OperationalReview("operational_bobbin_unavailable")
                    if context["context_digest"] != ref["context_digest"] or (
                        bobbin_context.context_version(str(capture.scope_snapshot_id), context["bobbin_id"], context["context_digest"])
                        != capture.context_version
                    ):
                        raise OperationalReview("operational_context_changed")
                    outcome = bobbin_service.submit_quality_capture(
                        connection, actor_id=principal.user_id, bobbin_id=context["bobbin_id"],
                        capture_id=capture.capture_id, form_code=capture.form_code,
                        device_key=capture.device_key, values=values,
                        request_id=request_id, sectors=principal.sectors, gate=gate,
                    )
                if outcome.capture.id != capture.capture_id or outcome.capture.form_version_number != capture.form_version:
                    raise OperationalReview("operational_form_version_changed")
                if outcome.capture.status not in ("submitted", "closed"):
                    raise StoreUnavailable("operational_submission_incomplete")
                return OperationalRegistration(capture_id=capture.capture_id)
        except (AuthorizationDenied, ResourceNotFound):
            raise OperationalReview("operational_not_authorized") from None
        except (CaptureIdempotencyConflictError,):
            raise OperationalReview("operational_id_conflict") from None
        except (CaptureValidationError, FormNotAvailableError, UnsupportedFormDefinitionError, UnsupportedFormError,
                BobbinNotFoundError, DeviceInactiveError, DeviceMachineMismatchError):
            raise OperationalReview("operational_validation_failed") from None
        except AuthorizationUnavailable:
            raise StoreUnavailable("operational_authz_unavailable") from None
