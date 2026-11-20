"""OFF-04.6: CENTRAL validation of a received offline capture, with the SAME code the online Quality routes use (no second implementation of any rule or calculation).

Read-only: it opens its own read connection, loads the exact published definition for the machine, and runs the online preparation (`_prepare_values`: types, required, options,
unknown keys, calculated fields refused from the client, server calculations; and for bobbin forms the profile rows, the declared bobbin number and the minimum integers). Nothing is
written, no permission is created, nothing is approved. The result is a verdict the receiver stores with the receipt; a capture that fails validation is KEPT and goes to review."""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable, Optional
from uuid import UUID

from app import capture_service as cs
from app.bobbins.errors import BobbinNotFoundError
from app.capture_errors import CaptureValidationError, FormNotAvailableError, UnsupportedFormDefinitionError
from app.offline_quality import bobbin_context
from app.offline_quality.registry import BOBBIN, MACHINE, spec_for
from app.quality import capture_service as bobbin_service
from app.quality import machine_capture_service as machine_service

logger = logging.getLogger("vinto.offline.central")
MAX_ERRORS = 50
QUALITY_AREA = "quality"


def code_for(message: str) -> str:
    """Stable, value-free code for a validator message (the messages themselves name the field and never echo the submitted value)."""
    m = message.lower()
    for needle, code in (("entero no negativo", "minimum"), ("obligatorio", "required"), ("campo desconocido", "unknown"), ("calculado por el sistema", "calculated"), ("debe ser texto", "type"), ("debe ser un entero", "type"),
                         ("debe ser un número", "type"), ("debe ser verdadero", "type"), ("debe ser una fecha", "type"), ("debe ser una hora", "type"), ("valor no permitido", "option"),
                         ("fuera de rango", "range"), ("supera", "too_long"), ("demasiados dígitos", "range"), ("no coincide con la bobina", "bobbin_mismatch"), ("fila incompleta", "profile_row"),
                         ("al menos una posición", "profile_empty"), ("entero no negativo", "minimum")):
        if needle in m:
            return code
    return "invalid"


def split_errors(text: str, known=()) -> list[tuple[str, str]]:
    """`known` = the field keys of the definition: a message that starts with a known key without a colon (e.g. the declared bobbin number) is attributed to that field."""
    out = []
    for part in [p.strip() for p in re.split(r";\s+(?=[\w.\[\]-]+:\s)", text) if p.strip()]:
        key, _, rest = part.partition(":")
        key = key.strip() if rest and " " not in key.strip() else "*"
        first = part.split(" ", 1)[0]
        if key == "*" and first in known:
            key = first
        out.append((key, code_for(part)))
    return out[:MAX_ERRORS]


@dataclass(frozen=True)
class Verdict:
    ok: bool
    errors: tuple = ()                 # ((field key | "*", code), ...)
    calculated: dict = field(default_factory=dict)   # key -> exact text (server calculations)
    version_mismatch: bool = False     # the device prepared an older/other published version
    context_kind: Optional[str] = None  # "same" | "incompatible_change" for bobbin forms; None when not evaluated here
    published_version: Optional[int] = None


def _published_number(connection, version_id) -> int:
    return connection.execute("SELECT version_number FROM vinto_config.form_version WHERE id = %s", (version_id,)).fetchone()[0]


class QualityPayloadValidator:
    """`open_connection()` returns a context-managed psycopg connection with READ access to the catalog (the application role already has it)."""
    def __init__(self, open_connection: Callable[[], Any], *, evaluate_bobbin_context: bool = False, synthetic_bobbins=None) -> None:
        self._open = open_connection
        self._bobbin_context = evaluate_bobbin_context
        self._synthetic = synthetic_bobbins     # None: the bobbins are the database's; otherwise a SyntheticBobbinSource (QA pilot)

    def validate(self, principal, capture) -> Verdict:
        spec = spec_for(capture.form_code)
        if spec is None:
            return Verdict(False, (("*", "unsupported_form"),))
        body = capture.payload
        values = body.get("payload") if isinstance(body, dict) else None
        if not isinstance(values, dict):
            return Verdict(False, (("*", "payload_shape"),))
        try:
            with self._open() as connection:
                with connection.transaction():
                    return self._validate(connection, principal, capture, spec, body, values)
        except Exception:  # a validator outage must never lose or approve the capture: the receiver keeps it for review
            logger.warning("central validation unavailable for form %s", capture.form_code)
            raise

    def _validate(self, connection, principal, capture, spec, body, values) -> Verdict:
        machine = connection.execute("SELECT m.id FROM vinto_master.machine m WHERE m.code = %s AND m.active", (capture.machine_code,)).fetchone()
        if machine is None:
            return Verdict(False, (("*", "machine_unavailable"),))
        machine_id = machine[0]
        context_kind = None
        known: set = set()
        try:
            if spec.kind == MACHINE:
                version_id = cs.published_form_version(connection, capture.form_code, machine_id, area=QUALITY_AREA)
                fields, clean = machine_service._prepare_values(connection, version_id, capture.form_code, values)
                known = {f.key for f in fields}
            else:
                ref = body.get("bobbin") if isinstance(body.get("bobbin"), dict) else None
                if ref is None or not isinstance(ref.get("bobbin_id"), str):
                    return Verdict(False, (("*", "bobbin_required"),))
                ctx = (bobbin_context.load_by_id(connection, ref["bobbin_id"], principal.sectors) if self._synthetic is None else self._synthetic.get(ref["bobbin_id"]))
                if ctx is None:
                    return Verdict(False, (("*", "bobbin_unknown"),), context_kind="incompatible_change" if self._bobbin_context else None)
                if ctx["machine_code"] != capture.machine_code:
                    return Verdict(False, (("*", "bobbin_machine_mismatch"),), context_kind="incompatible_change" if self._bobbin_context else None)
                if self._bobbin_context:
                    expected = bobbin_context.context_version(str(capture.scope_snapshot_id), ctx["bobbin_id"], ctx["context_digest"])
                    context_kind = "same" if expected == capture.context_version else "incompatible_change"
                is_mother = ctx["is_mother"]
                version_id = (bobbin_service._published_mother_form_version(connection, capture.form_code, machine_id) if is_mother
                              else cs.published_form_version(connection, capture.form_code, machine_id, area=QUALITY_AREA))
                fields, manual, clean = bobbin_service._prepare_values(connection, version_id, capture.form_code, values)
                known = {f.key for f in fields}
                if self._synthetic is None:
                    bobbin_service._check_declared_bobbin(connection, capture.form_code, UUID(ctx["bobbin_id"]), clean, manual)
                else:   # same rule as the online route, against the synthetic bobbin's code
                    key = bobbin_service.BOBBIN_CODE_FIELDS.get(capture.form_code)
                    if key is not None and key in {f.key for f in manual}:
                        declared = clean.get(key)
                        if not isinstance(declared, str) or declared.strip() != ctx["bobbin_code"]:
                            raise CaptureValidationError(f"{key} no coincide con la bobina seleccionada")
                bobbin_service._check_minimums(capture.form_code, clean)
        except CaptureValidationError as error:
            return Verdict(False, tuple(split_errors(str(error), known)), context_kind=context_kind)
        except FormNotAvailableError:
            return Verdict(False, (("*", "form_not_available"),), context_kind=context_kind)
        except (UnsupportedFormDefinitionError, BobbinNotFoundError):
            return Verdict(False, (("*", "definition_unsupported"),), context_kind=context_kind)
        published = _published_number(connection, version_id)
        calculated = {f.key: _text(clean[f.key]) for f in fields if f.source == "calculated" and f.key in clean}
        return Verdict(True, (), calculated, version_mismatch=published != capture.form_version, context_kind=context_kind, published_version=published)


def _text(value) -> str:
    return str(value)
