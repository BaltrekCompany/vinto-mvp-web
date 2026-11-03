"""Esquemas HTTP de asignaciones. La salida no incluye datos de auditoría ni ids internos de turno o artículo."""

from datetime import date, datetime
from typing import Literal
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer, model_validator

from app.assignments.service import ActivationPlan, ActivationResult, ActiveAssignment, ActiveLines, AssignmentView, BulkResult


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
    finished_assignment_id: UUID | None  # solo si se finalizó exactamente una; la lista completa va en finished_assignment_ids
    finished_assignment_ids: list[UUID] = []
    assignment: AssignmentOut


class ActiveItemOut(BaseModel):
    assignment: AssignmentOut
    stale: bool | None


class CurrentShiftOut(BaseModel):
    code: str
    name: str
    operating_date: date


class ActiveOut(BaseModel):
    assignment: AssignmentOut | None
    current_shift: CurrentShiftOut | None
    stale: bool | None


class ActiveLinesOut(BaseModel):
    """Contrato multilínea: todas las asignaciones activas de la máquina; ninguna se elige por el cliente ni por el servidor."""

    current_shift: CurrentShiftOut | None
    assignments: list[ActiveItemOut]


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
                         finished_assignment_id=result.finished_assignment_id,
                         finished_assignment_ids=list(result.finished_assignment_ids), assignment=assignment_out(result.assignment))


def _current_shift(code, name, operating_date):
    return None if code is None else CurrentShiftOut(code=code, name=name, operating_date=operating_date)


def active_out(result: ActiveAssignment) -> ActiveOut:
    return ActiveOut(assignment=assignment_out(result.assignment) if result.assignment else None,
                     current_shift=_current_shift(result.current_shift_code, result.current_shift_name, result.current_operating_date), stale=result.stale)


def active_lines_out(result: ActiveLines) -> ActiveLinesOut:
    return ActiveLinesOut(current_shift=_current_shift(result.current_shift_code, result.current_shift_name, result.current_operating_date),
                          assignments=[ActiveItemOut(assignment=assignment_out(i.assignment), stale=i.stale) for i in result.items])


class ActivateAllIn(BaseModel):
    """Vista previa (`dry_run=true`) o confirmación (`dry_run=false` + `plan_hash`). Nunca máquina, turno, fecha ni versión operativa."""

    model_config = ConfigDict(extra="forbid")

    dry_run: bool
    plan_hash: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def _hash_only_to_confirm(self):
        if self.dry_run and self.plan_hash is not None:
            raise ValueError("plan_hash solo se envía al confirmar (dry_run=false)")
        if not self.dry_run and self.plan_hash is None:
            raise ValueError("plan_hash es obligatorio al confirmar (dry_run=false)")
        return self


class PlanArticleOut(BaseModel):
    code: str
    description: str


class PlanLineOut(BaseModel):
    baseline_line_id: UUID
    line_code: str
    pv_reference: str
    article: PlanArticleOut
    machine: NameCodeOut
    shift: NameCodeOut | None
    operating_date: date | None
    action: Literal["activate", "already_active", "blocked"]
    reason: str | None
    assignment_id: UUID | None

    @field_serializer("operating_date")
    def _date(self, value):
        return None if value is None else value.isoformat()


class PlanExpiredOut(BaseModel):
    assignment_id: UUID
    machine: NameCodeOut
    line_code: str


class PlanConflictOut(BaseModel):
    assignment_id: UUID
    machine: NameCodeOut
    work_order: WorkOrderRefOut
    line_code: str
    expired: bool | None


class PlanSummaryOut(BaseModel):
    activate: int
    already_active: int
    blocked: int
    expired_to_finish: int
    conflicts: int


class ActivateAllOut(BaseModel):
    dry_run: bool
    outcome: Literal["preview", "applied", "already_in_effect"]
    work_order: WorkOrderRefOut
    status: str
    plan_hash: str
    can_confirm: bool
    summary: PlanSummaryOut
    lines: list[PlanLineOut]
    expired: list[PlanExpiredOut]
    conflicts: list[PlanConflictOut]
    activated: list[AssignmentOut] = []
    already_active: list[AssignmentOut] = []
    finished: list[AssignmentOut] = []


def activate_all_out(result: BulkResult, plan_hash: str | None = None) -> ActivateAllOut:
    plan: ActivationPlan = result.plan
    lines = [PlanLineOut(
        baseline_line_id=l.baseline_line_id, line_code=l.line_code, pv_reference=l.pv_reference,
        article=PlanArticleOut(code=l.article_code, description=l.article_description), machine=NameCodeOut(code=l.machine_code, name=l.machine_name),
        shift=None if l.shift_code is None else NameCodeOut(code=l.shift_code, name=l.shift_name), operating_date=l.operating_date,
        action=l.action, reason=l.reason, assignment_id=l.assignment_id) for l in plan.lines]
    count = lambda action: sum(1 for l in plan.lines if l.action == action)  # noqa: E731
    return ActivateAllOut(
        dry_run=result.outcome == "preview", outcome=result.outcome, work_order=WorkOrderRefOut(id=plan.work_order_id, number=plan.number),
        status=plan.status, plan_hash=plan_hash or plan.plan_hash, can_confirm=plan.can_confirm,
        summary=PlanSummaryOut(activate=count("activate"), already_active=count("already_active"), blocked=count("blocked"),
                               expired_to_finish=len(plan.expired), conflicts=len(plan.conflicts)),
        lines=lines, expired=[PlanExpiredOut(assignment_id=e.assignment_id, machine=NameCodeOut(code=e.machine_code, name=e.machine_name), line_code=e.line_code) for e in plan.expired],
        conflicts=[PlanConflictOut(assignment_id=c.assignment_id, machine=NameCodeOut(code=c.machine_code, name=c.machine_name),
                                   work_order=WorkOrderRefOut(id=c.work_order_id, number=c.work_order_number), line_code=c.line_code, expired=c.expired)
                   for c in plan.conflicts],
        activated=[assignment_out(v) for v in result.activated], already_active=[assignment_out(v) for v in result.already_active],
        finished=[assignment_out(v) for v in result.finished])
