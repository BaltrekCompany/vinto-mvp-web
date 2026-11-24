"""OFF-04.8P: opt-in, database-backed industrial context check for Quality.

A machine capture belongs to its signed snapshot. A by-bobbin capture must
reference the immutable F3 source context, by ID and digest; active assignments
and release decisions are deliberately irrelevant. No app.main registration.
"""
from __future__ import annotations

from typing import Callable

from app.offline_capture.service import ContextVerdict
from app.offline_quality import bobbin_context
from app.offline_quality.registry import BOBBIN, MACHINE, spec_for


class RegisteredQualityContext:
    def __init__(self, connect: Callable, *, sectors):
        if not callable(connect):
            raise TypeError("quality_context_connection_required")
        self._connect = connect
        self._sectors = sectors

    def evaluate(self, capture) -> ContextVerdict:
        spec = spec_for(capture.form_code)
        if spec is None or capture.scope_snapshot_id is None:
            return ContextVerdict("unverifiable")
        if spec.kind == MACHINE:
            if "bobbin" in capture.payload:
                return ContextVerdict("incompatible_change")
            return ContextVerdict(
                "same" if capture.context_version == str(capture.scope_snapshot_id)
                else "incompatible_change"
            )
        if spec.kind != BOBBIN:
            return ContextVerdict("unverifiable")
        ref = capture.payload.get("bobbin")
        if not isinstance(ref, dict) or set(ref) != {"bobbin_id", "context_digest"}:
            return ContextVerdict("unverifiable")
        with self._connect() as connection:
            actual = bobbin_context.load_by_id(
                connection, ref["bobbin_id"], self._sectors,
            )
        if actual is None:
            return ContextVerdict("unverifiable")
        if (
            actual["machine_code"] != capture.machine_code
            or actual["context_digest"] != ref["context_digest"]
            or capture.context_version != bobbin_context.context_version(
                str(capture.scope_snapshot_id),
                actual["bobbin_id"], actual["context_digest"],
            )
        ):
            return ContextVerdict("incompatible_change")
        return ContextVerdict("same")
