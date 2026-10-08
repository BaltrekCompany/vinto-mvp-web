"""Esquemas HTTP de capturas de Calidad. El cliente solo envía capture_id, form_code, device_key y values; la Bobina viene en la ruta y
todo el contexto productivo se deriva de ella (extra="forbid"). La salida no incluye auditoría, dispositivo ni assignment_id."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict, Field

from app.capture_schemas import CodeNameOut, FormOut, LineOut, ArticleOut, WorkOrderRefOut
from app.quality.capture_service import QualityCaptureResult, QualityCaptureView


class QualityCaptureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: UUID4
    form_code: str = Field(min_length=1, max_length=64)
    device_key: UUID
    values: dict[str, Any]


class BobbinRefOut(BaseModel):
    id: UUID
    code: str


class QualityCaptureOut(BaseModel):
    id: UUID
    status: str
    revision: int
    captured_at: datetime
    submitted_at: datetime | None
    form: FormOut
    bobbin: BobbinRefOut
    machine: CodeNameOut
    shift: CodeNameOut
    operating_date: date
    work_order: WorkOrderRefOut
    line: LineOut
    values: dict[str, Any]  # decimales como texto para no perder precisión


class QualityCaptureResultOut(BaseModel):
    created: bool
    already_submitted: bool
    capture: QualityCaptureOut


def quality_capture_out(v: QualityCaptureView) -> QualityCaptureOut:
    return QualityCaptureOut(
        id=v.id, status=v.status, revision=v.revision, captured_at=v.captured_at, submitted_at=v.submitted_at,
        form=FormOut(code=v.form_code, version_number=v.form_version_number, name=v.form_name), bobbin=BobbinRefOut(id=v.bobbin_id, code=v.bobbin_code),
        machine=CodeNameOut(code=v.machine_code, name=v.machine_name), shift=CodeNameOut(code=v.shift_code, name=v.shift_name), operating_date=v.operating_date,
        work_order=WorkOrderRefOut(id=v.work_order_id, number=v.work_order_number),
        line=LineOut(id=v.line_id, line_code=v.line_code, pv_reference=v.pv_reference, article=ArticleOut(code=v.article_code, description=v.article_description)),
        values=v.values)


def quality_capture_result_out(result: QualityCaptureResult) -> QualityCaptureResultOut:
    return QualityCaptureResultOut(created=result.created, already_submitted=result.already_submitted, capture=quality_capture_out(result.capture))
