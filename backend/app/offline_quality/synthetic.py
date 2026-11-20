"""OFF-04.6: SYNTHETIC bobbin contexts of the QA pilot (the isolated QA database holds no industrial bobbin). Registry configured by the operator, never derived from the database.

Same context fields and digest as the real (database) contexts, so the device and the receiver treat both identically."""
from __future__ import annotations

import json
from datetime import date
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, StringConstraints, ValidationError, field_validator

from app.offline_quality import bobbin_context

MAX_BOBBINS = 50
Code = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_.-]{1,48}$")]
Text = Annotated[str, StringConstraints(min_length=1, max_length=200)]


class SyntheticBobbin(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)
    synthetic: Literal[True]
    bobbin_id: UUID
    machine_code: Code
    bobbin_code: Code
    work_order: Annotated[str, StringConstraints(min_length=1, max_length=48)]
    line_code: Annotated[str, StringConstraints(min_length=1, max_length=48)]
    pv_reference: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    article_code: Annotated[str, StringConstraints(min_length=1, max_length=64)]
    article_description: Text
    shift_code: Annotated[str, StringConstraints(min_length=1, max_length=16)]
    operating_date: str

    @field_validator("operating_date")
    @classmethod
    def _iso_date(cls, value: str) -> str:
        date.fromisoformat(value)
        return value

    def context(self) -> dict:
        ctx = {"bobbin_id": str(self.bobbin_id), "bobbin_code": self.bobbin_code, "machine_code": self.machine_code, "is_mother": False, "work_order": self.work_order,
               "line_code": self.line_code, "pv_reference": self.pv_reference, "article_code": self.article_code, "article_description": self.article_description,
               "shift_code": self.shift_code, "operating_date": self.operating_date}
        ctx["context_digest"] = bobbin_context.context_digest(ctx)
        return ctx


def parse_bobbins(raw) -> tuple[SyntheticBobbin, ...]:
    if raw is None or raw == "":
        return ()
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
        if not isinstance(data, list) or len(data) > MAX_BOBBINS:
            raise ValueError("shape")
        out = tuple(SyntheticBobbin.model_validate(item) for item in data)
        if len({b.bobbin_id for b in out}) != len(out):
            raise ValueError("duplicate")
        return out
    except (ValueError, ValidationError):
        raise ValueError("bobbins_invalid") from None


class SyntheticBobbinSource:
    """Lookup used by the central validator in the pilot instead of the (empty) industrial tables."""
    synthetic = True

    def __init__(self, bobbins) -> None:
        self._by_id = {str(b.bobbin_id): b for b in bobbins}

    def get(self, bobbin_id) -> dict | None:
        b = self._by_id.get(str(bobbin_id).lower())
        return b.context() if b else None
