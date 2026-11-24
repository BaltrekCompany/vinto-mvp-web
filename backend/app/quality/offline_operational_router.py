"""OFF-04.8 — explicit, opt-in composition of the real Quality offline receiver.

Not imported by app.main. Only a separately isolated, authorized QA app may
include the returned router. This module never installs migrations, enables
capture issuance, or grants user/machine/form permissions.

All dependencies use the same configured PostgreSQL database:
 - signed registered CAPTURE authority (preflight and receipt transaction);
 - published-form validation using the exact ONLINE Quality service rules;
 - actual F3 historic context, scoped to the authenticated user in validator;
 - effective MF-13 enforce within the atomic operational receipt transaction.
"""
from __future__ import annotations

from typing import Callable

from app.offline_capture.router import create_offline_capture_router
from app.offline_capture.service import ContextVerdict
from app.offline_capture.store import PgOfflineCaptureStore
from app.offline_quality.central import QualityPayloadValidator
from app.offline_quality.registry import MACHINE, BOBBIN, spec_for
from app.quality.offline_capture_authorizer import RegisteredCaptureAuthorizer
from app.quality.offline_operational_binding import registered_scope_promoter


class QualityReceiverContext:
    """Machine snapshot is immutable; F3 context evaluated by central validator.

    ContextProvider has no user argument. For F3 records the validator MUST
    consult the actual F3 against the authenticated user's sectors, rather
    than relying on a global unscoped lookup.
    """

    def evaluate(self, capture) -> ContextVerdict:
        spec = spec_for(capture.form_code)
        if capture.scope_snapshot_id is None or spec is None:
            return ContextVerdict("unverifiable")
        if spec.kind == MACHINE:
            if "bobbin" in capture.payload:
                return ContextVerdict("incompatible_change")
            return ContextVerdict(
                "same" if capture.context_version == str(capture.scope_snapshot_id)
                else "incompatible_change"
            )
        if spec.kind == BOBBIN:
            # QualityPayloadValidator(evaluate_bobbin_context=True) runs
            # scoped F3 lookup; the receiver promotes 'unverifiable' to
            # 'same' only on the validator's explicit SAME verdict.
            return ContextVerdict("unverifiable")
        return ContextVerdict("unverifiable")


def create_operational_quality_router(
    *, open_connection: Callable, trusted_public_key_b64url: str,
    enabled: bool = False,
):
    """Compose fully real receiver only on explicit opt-in.

    The caller is responsible for a DISPOSABLE/isolated QA database, applied
    0032/0033 schemas and verified user auth; no production mount occurs.
    """
    if not enabled:
        return create_offline_capture_router(enabled=False)
    authorizer = RegisteredCaptureAuthorizer(
        open_connection, trusted_public_key_b64url=trusted_public_key_b64url,
    )
    validator = QualityPayloadValidator(open_connection, evaluate_bobbin_context=True)
    return create_offline_capture_router(
        store=PgOfflineCaptureStore(open_connection),
        enabled=True, authorizer=authorizer, context=QualityReceiverContext(),
        validator=validator,
        promoter=registered_scope_promoter(
            trusted_public_key_b64url=trusted_public_key_b64url,
        ),
    )
