"""Wire contract of the offline capture receiver (OFF-04.4). Pure: no I/O, no database, no framework state."""
from __future__ import annotations

import hashlib
import json
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

# ---- reason codes (stable strings the client engine maps to states) ----
R_AUTHOR_MISMATCH = "author_mismatch"             # authenticated user is not the capture's original author
R_NOT_AUTHORIZED = "capture_not_authorized"       # no industrial capture grant for that machine/form
R_READ_ONLY_SCOPE = "read_only_scope"             # readiness-only (consultation) snapshot never authorises captures
R_AUTHOR_IMMUTABLE = "author_immutable"           # the capture_id already belongs to another author
R_PAYLOAD_MISMATCH = "payload_mismatch"           # same capture_id, different content
R_INTEGRITY = "integrity_mismatch"                # declared checksum does not match the received payload
R_FORM_VERSION = "form_version_incompatible"
R_CONTEXT_COMPAT = "context_changed_after_prepare"  # warning
R_CONTEXT_INCOMPATIBLE = "context_incompatible"
R_CONTEXT_UNVERIFIABLE = "context_unverifiable"
R_UNSUPPORTED_VALUE = "unsupported_value"
R_UNAVAILABLE = "receiver_unavailable"
R_DISABLED = "receiver_disabled"

OUTCOMES = ("accepted", "accepted_warning", "review", "conflict")

MachineCode = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]
FormCode = Annotated[str, StringConstraints(pattern=r"^VINTO-[A-Z0-9-]{2,40}$")]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class CaptureIn(BaseModel):
    """POST body. `capture_id` is the idempotency key; `author_user_id` is the ORIGINAL author and never changes."""
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)
    capture_id: UUID
    author_user_id: UUID
    device_key: UUID
    form_code: FormCode
    form_version: int = Field(ge=1, le=10_000)
    machine_code: MachineCode
    scope_snapshot_id: UUID | None = None
    context_version: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    payload_sha256: Sha256Hex
    payload: dict[str, Any]


def _canon(value: Any) -> Any:
    """Sorted keys, JSON scalars only. Floats are refused: their text form differs between languages."""
    if isinstance(value, dict):
        return {k: _canon(value[k]) for k in sorted(value)}
    if isinstance(value, list):
        return [_canon(v) for v in value]
    if value is None or isinstance(value, (str, bool, int)):
        return value
    raise ValueError(R_UNSUPPORTED_VALUE)


def canonical_sha256(payload: Any) -> str:
    """Same canonical hash as the client engine (`payloadHash`): sorted keys, compact JSON, UTF-8, SHA-256 hex."""
    text = json.dumps(_canon(payload), separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def server_id_for(seq: int) -> str:
    return "srv-" + str(seq).rjust(6, "0")


def public_body(*, outcome: str, capture_id: str, payload_sha256: str, server_id: str | None, warnings: list[str] | None = None,
                reason: str | None = None) -> dict[str, Any]:
    """Shape shared by every reply. Technical acceptance is NEVER industrial approval, release or an order change."""
    return {"outcome": outcome, "capture_id": capture_id, "payload_sha256": payload_sha256, "server_id": server_id,
            "warnings": warnings or [], "reason": reason, "technical_acceptance": outcome in ("created", "duplicate", "review"),
            "industrial_approval": False}
