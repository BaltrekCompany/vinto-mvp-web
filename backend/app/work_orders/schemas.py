"""Esquemas HTTP de órdenes de trabajo. La salida no incluye datos de auditoría ni internals."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.work_orders.service import LineInput, WorkOrderView


class LineIn(BaseModel):
    """Solo el cliente aporta PV, código de artículo, cantidad, fecha y, opcionalmente, el CÓDIGO de la máquina de la línea.

    Sin `machine_code` rige la máquina de cabecera (contrato anterior). Descripción, unidad, versión e ids internos (`machine_id`, versiones
    operativas) los resuelve el servidor; `extra="forbid"` rechaza cualquier otro campo con 422."""

    model_config = ConfigDict(extra="forbid")

    pv_reference: str = Field(min_length=1, max_length=100)
    article_code: str = Field(min_length=1, max_length=64)
    quantity: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    due_date: date
    machine_code: str | None = Field(default=None, min_length=1, max_length=64)

    def to_domain(self) -> LineInput:
        return LineInput(self.pv_reference, self.article_code, self.quantity, self.due_date, self.machine_code)


class DraftLineFieldsIn(BaseModel):
    """Solo cuatro campos editables; la máquina no forma parte de este contrato."""

    model_config = ConfigDict(extra="forbid")

    pv_reference: str = Field(min_length=1, max_length=100)
    article_code: str = Field(min_length=1, max_length=64)
    quantity: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    due_date: date

    def to_domain(self) -> LineInput:
        return LineInput(self.pv_reference, self.article_code, self.quantity, self.due_date)


class EditDraftLineIn(BaseModel):
    """CAS contra la última línea leída: ningún cambio silencioso entre dos jefaturas."""

    model_config = ConfigDict(extra="forbid")

    expected: DraftLineFieldsIn
    replacement: DraftLineFieldsIn
    reason: str = Field(min_length=10, max_length=300)


class ReprogramPublishedLineIn(BaseModel):
    """E2-B: explicit revision expected; no machine or identity fields accepted."""

    model_config = ConfigDict(extra="forbid")

    expected_version: int = Field(ge=1)
    expected: DraftLineFieldsIn
    replacement: DraftLineFieldsIn
    reason: str = Field(min_length=10, max_length=300)


class RevisionFieldsOut(BaseModel):
    pv_reference: str
    article_code: str
    quantity: Decimal
    due_date: date

    @field_serializer("quantity", when_used="json")
    def quantity_as_number(self, value: Decimal) -> float:
        return float(value)


class RevisionOut(BaseModel):
    version_number: int
    previous_version: int
    line_code: str
    reason: str
    changed_at: datetime
    changed_by_id: UUID
    changed_by_name: str
    before: RevisionFieldsOut
    after: RevisionFieldsOut


class CreateWorkOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine_code: str = Field(min_length=1, max_length=64)
    lines: list[LineIn] = Field(min_length=1, max_length=200)


class MachineOut(BaseModel):
    code: str
    name: str


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
    machine: MachineOut  # máquina de ESTA línea (igual a la de cabecera en las OT de una sola máquina)

    @field_serializer("quantity", when_used="json")
    def quantity_as_number(self, value: Decimal) -> float:
        return float(value)  # a lo sumo 15 dígitos significativos: exacto en un double


class BaselineOut(BaseModel):
    id: UUID
    version_number: int
    published_at: datetime | None
    lines: list[LineOut]


class WorkOrderOut(BaseModel):
    id: UUID
    number: str
    status: str
    machine: MachineOut
    baseline: BaselineOut
    programming: BaselineOut | None = None  # E2-B: latest versioned program, baseline remains original


def _version_out(version) -> BaselineOut:
    return BaselineOut(
        id=version.id, version_number=version.version_number, published_at=version.published_at,
        lines=[LineOut(
            id=l.id, line_code=l.line_code, pv_reference=l.pv_reference,
            article=ArticleOut(code=l.article_code, description=l.article_description),
            quantity=l.quantity, unit=l.unit, due_date=l.due_date,
            machine=MachineOut(code=l.machine_code, name=l.machine_name),
        ) for l in version.lines])


def work_order_out(view: WorkOrderView) -> WorkOrderOut:
    return WorkOrderOut(
        id=view.id, number=view.number, status=view.status,
        machine=MachineOut(code=view.machine_code, name=view.machine_name),
        baseline=_version_out(view.baseline),
        programming=_version_out(view.programming) if view.programming is not None else None,
    )
