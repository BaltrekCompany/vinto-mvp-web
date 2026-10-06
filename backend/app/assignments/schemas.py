"""Esquemas HTTP de asignaciones. La salida no incluye datos de auditoría ni ids internos de turno o artículo."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, field_serializer

from app.assignments.service import ActivationResult, ActiveAssignment, AssignmentView


class ActivateIn(BaseModel):
    """El cliente envía la OT y la línea BASE; nunca máquina, turno, fecha ni ids de la versión operativa."""

    model_config = ConfigDict(extra="forbid")

    work_order_id: UUID
    baseline_line_id: UUID


class NameCodeOut(BaseModel):
    code: str
    name: str


class WorkOrderRefOut(BaseModel):
    id: UUID
    number: str


class OperationalOut(BaseModel):
    version_number: int


class ArticleOut(BaseModel):
    code: str
    description: str


class LineOut(BaseModel):
    id: UUID
    line_code: str
    pv_reference: str
    article: ArticleOut
    quantity: Decimal
    unit: str
    due_date: date

    @field_serializer("quantity", when_used="json")
    def quantity_as_number(self, value: Decimal) -> float:
        return float(value)


class AssignedByOut(BaseModel):
    id: UUID
    display_name: str


class AssignmentOut(BaseModel):
    id: UUID
    status: str
    operating_date: date
    created_at: datetime
    finished_at: datetime | None
    machine: NameCodeOut
    shift: NameCodeOut
    work_order: WorkOrderRefOut
    operational: OperationalOut
    line: LineOut
    assigned_by: AssignedByOut


class ActivationOut(BaseModel):
    created: bool
    already_active: bool
    finished_assignment_id: UUID | None
    assignment: AssignmentOut


class CurrentShiftOut(BaseModel):
    code: str
    name: str
    operating_date: date


class ActiveOut(BaseModel):
    assignment: AssignmentOut | None
    current_shift: CurrentShiftOut | None
    stale: bool | None


def assignment_out(view: AssignmentView) -> AssignmentOut:
    line = view.line
    return AssignmentOut(
        id=view.id, status=view.status, operating_date=view.operating_date, created_at=view.created_at, finished_at=view.finished_at,
        machine=NameCodeOut(code=view.machine_code, name=view.machine_name), shift=NameCodeOut(code=view.shift_code, name=view.shift_name),
        work_order=WorkOrderRefOut(id=view.work_order_id, number=view.work_order_number),
        operational=OperationalOut(version_number=view.operational_version_number),
        line=LineOut(id=line.id, line_code=line.line_code, pv_reference=line.pv_reference,
                     article=ArticleOut(code=line.article_code, description=line.article_description),
                     quantity=line.quantity, unit=line.unit, due_date=line.due_date),
        assigned_by=AssignedByOut(id=view.assigned_by_id, display_name=view.assigned_by_name))


def activation_out(result: ActivationResult) -> ActivationOut:
    return ActivationOut(created=result.created, already_active=result.already_active,
                         finished_assignment_id=result.finished_assignment_id, assignment=assignment_out(result.assignment))


def active_out(result: ActiveAssignment) -> ActiveOut:
    shift = None
    if result.current_shift_code is not None:
        shift = CurrentShiftOut(code=result.current_shift_code, name=result.current_shift_name, operating_date=result.current_operating_date)
    return ActiveOut(assignment=assignment_out(result.assignment) if result.assignment else None, current_shift=shift, stale=result.stale)
