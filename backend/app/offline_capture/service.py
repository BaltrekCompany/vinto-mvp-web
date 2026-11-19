"""Receiver pipeline (OFF-04.4), in five separated phases:

  1. RECEIVE      shape + checksum of the request (contract.py, plus the integrity check here)
  2. AUTHORISE    authenticated identity == original author; capture authorisation for (machine, form) via an injected authoriser
  3. PERSIST      idempotent insert keyed by `capture_id` in ONE transaction (store.py); duplicates / reused ids detected here
  4. EVALUATE     industrial-context evaluation of a NEWLY persisted capture (injected provider); never changes the stored capture
  5. RECONCILE    result (outcome, reason, warnings, response) persisted in the same transaction and reused verbatim for retries

Technical acceptance is not industrial approval: nothing here approves, releases or modifies any industrial record.
The default authoriser denies everything: readiness-only (consultation) packages and snapshots never authorise captures.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol
from uuid import UUID

from app.auth.service import AuthenticatedUser
from app.offline_capture import contract as C
from app.offline_capture.store import NewReceipt, OfflineCaptureStore, Receipt, StoreUnavailable


@dataclass(frozen=True)
class AuthzDecision:
    allowed: bool
    reason: Optional[str] = None


class CaptureAuthorizer(Protocol):
    def authorize(self, principal: AuthenticatedUser, capture: C.CaptureIn) -> AuthzDecision: ...


class DenyAllAuthorizer:
    """Default: no capture authority exists for readiness-only packages, so nothing is authorised."""
    def authorize(self, principal, capture):
        return AuthzDecision(False, C.R_READ_ONLY_SCOPE if capture.scope_snapshot_id else C.R_NOT_AUTHORIZED)


@dataclass(frozen=True)
class ContextVerdict:
    kind: str    # same | compatible_change | incompatible_change | unknown_form_version | unverifiable
    detail: Optional[str] = None


class ContextProvider(Protocol):
    def evaluate(self, capture: C.CaptureIn) -> ContextVerdict: ...


class UnverifiableContext:
    """Default: the current industrial context cannot be proven, so every capture goes to central review (never silently accepted)."""
    def evaluate(self, capture):
        return ContextVerdict("unverifiable")


@dataclass(frozen=True)
class ReceiverReply:
    status: int
    body: dict


def _reply_from_receipt(r: Receipt, *, duplicate: bool) -> ReceiverReply:
    """Reuse the PERSISTED response of the first receipt; only the 'created' label becomes 'duplicate' for retries."""
    body = dict(r.response_body or {})
    status = int(r.response_status or 500)
    if duplicate and body.get("outcome") == "created":
        body["outcome"] = "duplicate"
        status = 200
    return ReceiverReply(status, body)


def _error(status: int, reason: str, outcome: str = "error", **extra) -> ReceiverReply:
    return ReceiverReply(status, {"outcome": outcome, "reason": reason, "technical_acceptance": False, "industrial_approval": False, **extra})


def receive_capture(store: OfflineCaptureStore, principal: AuthenticatedUser, capture: C.CaptureIn, *,
                    authorizer: CaptureAuthorizer, context: ContextProvider) -> ReceiverReply:
    cid = str(capture.capture_id)
    # 1) RECEIVE: the declared checksum must match the received payload (integrity conflict, nothing persisted as a capture)
    try:
        actual = C.canonical_sha256(capture.payload)
    except ValueError:
        return _error(422, C.R_UNSUPPORTED_VALUE)
    if actual != capture.payload_sha256:
        _try_event(store, capture, "integrity_conflict", principal, C.R_INTEGRITY)
        return _error(409, C.R_INTEGRITY, "conflict", capture_id=cid)
    # 2) AUTHORISE: identity first, then capture authority
    if principal.user_id != capture.author_user_id:
        return _error(403, C.R_AUTHOR_MISMATCH, capture_id=cid)
    decision = authorizer.authorize(principal, capture)
    if not decision.allowed:
        _try_event(store, capture, "denied", principal, decision.reason)
        return _error(403, decision.reason or C.R_NOT_AUTHORIZED, capture_id=cid)
    # 3) PERSIST (idempotent) + 4) EVALUATE + 5) RECONCILE, all in ONE transaction
    new = NewReceipt(capture.capture_id, capture.author_user_id, capture.device_key, capture.form_code, capture.form_version, capture.machine_code,
                     capture.scope_snapshot_id, capture.context_version, capture.payload_sha256, capture.payload)
    with store.transaction() as tx:
        created = tx.insert_received(new)
        if not created:
            existing = tx.get(capture.capture_id)
            if existing is None or existing.outcome == "received":
                raise StoreUnavailable("inconsistent_receipt")
            if existing.author_user_id != capture.author_user_id:
                tx.event(capture.capture_id, "author_conflict", capture.payload_sha256, principal.user_id, C.R_AUTHOR_IMMUTABLE)
                return _error(409, C.R_AUTHOR_IMMUTABLE, "conflict", capture_id=cid)
            if existing.payload_sha256 != capture.payload_sha256:
                tx.event(capture.capture_id, "payload_conflict", capture.payload_sha256, principal.user_id, C.R_PAYLOAD_MISMATCH)
                return _error(409, C.R_PAYLOAD_MISMATCH, "conflict", capture_id=cid)
            tx.event(capture.capture_id, "duplicate", capture.payload_sha256, principal.user_id, None)
            return _reply_from_receipt(existing, duplicate=True)
        verdict = context.evaluate(capture)
        seq = tx.get(capture.capture_id).server_seq
        server_id = C.server_id_for(seq)
        outcome, reason, warnings, status, label = "accepted", None, [], 201, "created"
        if verdict.kind == "compatible_change":
            outcome, warnings = "accepted_warning", [C.R_CONTEXT_COMPAT]
        elif verdict.kind == "incompatible_change":
            outcome, reason, status, label = "review", C.R_CONTEXT_INCOMPATIBLE, 202, "review"
        elif verdict.kind == "unknown_form_version":
            outcome, reason, status, label = "conflict", C.R_FORM_VERSION, 409, "conflict"
        elif verdict.kind != "same":
            outcome, reason, status, label = "review", C.R_CONTEXT_UNVERIFIABLE, 202, "review"
        body = C.public_body(outcome=label, capture_id=cid, payload_sha256=capture.payload_sha256,
                             server_id=server_id, warnings=warnings, reason=reason)
        tx.finalize(capture.capture_id, outcome=outcome, reason=reason, warnings=warnings, response_status=status, response_body=body)
        tx.event(capture.capture_id, "received", capture.payload_sha256, principal.user_id, outcome)
        return ReceiverReply(status, body)


def _try_event(store: OfflineCaptureStore, capture: C.CaptureIn, kind: str, principal: AuthenticatedUser, detail: Optional[str]) -> None:
    """Audit trail of rejected receipts; a failure to record it must not hide the rejection itself."""
    try:
        with store.transaction() as tx:
            tx.event(capture.capture_id, kind, capture.payload_sha256, principal.user_id, detail)
    except StoreUnavailable:
        pass


_LOOKUP = {"accepted": "accepted", "accepted_warning": "accepted_warning", "review": "review", "conflict": "conflict"}


def reconcile_capture(store: OfflineCaptureStore, principal: AuthenticatedUser, capture_id: UUID) -> ReceiverReply:
    """GET: only the ORIGINAL author can see a capture (anyone else gets the same 'not found': no existence leak)."""
    receipt = store.get(capture_id)
    if receipt is None or receipt.outcome == "received" or receipt.author_user_id != principal.user_id:
        return ReceiverReply(404, {"found": False})
    return ReceiverReply(200, {"found": True, "outcome": _LOOKUP[receipt.outcome], "capture_id": str(receipt.capture_id),
                               "payload_sha256": receipt.payload_sha256, "server_id": C.server_id_for(receipt.server_seq),
                               "warnings": receipt.warnings, "reason": receipt.reason, "technical_acceptance": receipt.outcome != "conflict",
                               "industrial_approval": False})
