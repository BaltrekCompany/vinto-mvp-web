"""Esquemas HTTP de los controles de Calidad por máquina. El cliente solo envía capture_id, form_code, device_key y values; la máquina viene en la ruta y el turno, la fecha operativa y el responsable
los resuelve el backend (extra="forbid"). `captured_at` es la hora de REGISTRO, no la hora del ensayo. La salida no incluye auditoría, dispositivo ni assignment_id."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict, Field

from app.capture_schemas import CodeNameOut, FormOut
from app.quality.machine_capture_service import MachineCaptureResult, MachineCaptureView


class MachineCaptureIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: UUID4
    form_code: str = Field(min_length=1, max_length=64)
    device_key: UUID
    values: dict[str, Any]


class RecordedByOut(BaseModel):
    id: UUID
    display_name: str


class MachineCaptureOut(BaseModel):
    id: UUID
    status: str
    revision: int
    captured_at: datetime  # hora de registro
    submitted_at: datetime | None
    form: FormOut
    machine: CodeNameOut
    shift: CodeNameOut
    operating_date: date
    recorded_by: RecordedByOut | None  # usuario autenticado que registró el control (informativo, no es una firma)
    values: dict[str, Any]  # decimales como texto para no perder precisión


class MachineCaptureResultOut(BaseModel):
    created: bool
    already_submitted: bool
    capture: MachineCaptureOut


def machine_capture_out(v: MachineCaptureView) -> MachineCaptureOut:
    return MachineCaptureOut(
        id=v.id, status=v.status, revision=v.revision, captured_at=v.captured_at, submitted_at=v.submitted_at,
        form=FormOut(code=v.form_code, version_number=v.form_version_number, name=v.form_name), machine=CodeNameOut(code=v.machine_code, name=v.machine_name),
        shift=CodeNameOut(code=v.shift_code, name=v.shift_name), operating_date=v.operating_date,
        recorded_by=RecordedByOut(id=v.recorded_by_id, display_name=v.recorded_by_name) if v.recorded_by_id else None, values=v.values)


def machine_capture_result_out(result: MachineCaptureResult) -> MachineCaptureResultOut:
    return MachineCaptureResultOut(created=result.created, already_submitted=result.already_submitted, capture=machine_capture_out(result.capture))
