"""Esquemas HTTP de capturas de producción. El cliente solo aporta el id de la captura, el formulario, la asignación, su
dispositivo y los valores; todo lo demás se deriva en el backend (extra="forbid"). La salida no incluye datos de auditoría."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict

from app.capture_service import CaptureResult, CaptureView


class CaptureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: UUID4
    form_code: str
    assignment_id: UUID
    device_key: UUID
    values: dict[str, Any]


class FormOut(BaseModel):
    code: str
    version_number: int
    name: str


class CodeNameOut(BaseModel):
    code: str
    name: str


class AssignmentRefOut(BaseModel):
    id: UUID


class WorkOrderRefOut(BaseModel):
    id: UUID
    number: str


class ArticleOut(BaseModel):
    code: str
    description: str


class LineOut(BaseModel):
    id: UUID
    line_code: str
    pv_reference: str
    article: ArticleOut


class CaptureOut(BaseModel):
    id: UUID
    status: str
    revision: int
    captured_at: datetime
    submitted_at: datetime | None
    form: FormOut
    machine: CodeNameOut
    shift: CodeNameOut
    operating_date: date
    assignment: AssignmentRefOut
    work_order: WorkOrderRefOut
    line: LineOut
    values: dict[str, Any]  # decimales como texto para no perder precisión


class CaptureResultOut(BaseModel):
    created: bool
    already_submitted: bool
    capture: CaptureOut


def capture_out(v: CaptureView) -> CaptureOut:
    return CaptureOut(
        id=v.id, status=v.status, revision=v.revision, captured_at=v.captured_at, submitted_at=v.submitted_at,
        form=FormOut(code=v.form_code, version_number=v.form_version_number, name=v.form_name),
        machine=CodeNameOut(code=v.machine_code, name=v.machine_name), shift=CodeNameOut(code=v.shift_code, name=v.shift_name),
        operating_date=v.operating_date, assignment=AssignmentRefOut(id=v.assignment_id),
        work_order=WorkOrderRefOut(id=v.work_order_id, number=v.work_order_number),
        line=LineOut(id=v.line_id, line_code=v.line_code, pv_reference=v.pv_reference, article=ArticleOut(code=v.article_code, description=v.article_description)),
        values=v.values)


def result_out(result: CaptureResult) -> CaptureResultOut:
    return CaptureResultOut(created=result.created, already_submitted=result.already_submitted, capture=capture_out(result.capture))
