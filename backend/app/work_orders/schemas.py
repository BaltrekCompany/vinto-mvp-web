"""Esquemas HTTP de órdenes de trabajo. La salida no incluye datos de auditoría ni internals."""

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.work_orders.service import LineInput, WorkOrderView


class LineIn(BaseModel):
    """Solo el cliente aporta PV, código de artículo, cantidad y fecha. Descripción, unidad y versión las resuelve el servidor."""

    model_config = ConfigDict(extra="forbid")

    pv_reference: str = Field(min_length=1, max_length=100)
    article_code: str = Field(min_length=1, max_length=64)
    quantity: Decimal = Field(gt=0, max_digits=15, decimal_places=3)
    due_date: date

    def to_domain(self) -> LineInput:
        return LineInput(self.pv_reference, self.article_code, self.quantity, self.due_date)


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


def work_order_out(view: WorkOrderView) -> WorkOrderOut:
    return WorkOrderOut(
        id=view.id, number=view.number, status=view.status,
        machine=MachineOut(code=view.machine_code, name=view.machine_name),
        baseline=BaselineOut(
            id=view.baseline.id, version_number=view.baseline.version_number, published_at=view.baseline.published_at,
            lines=[LineOut(id=l.id, line_code=l.line_code, pv_reference=l.pv_reference,
                           article=ArticleOut(code=l.article_code, description=l.article_description),
                           quantity=l.quantity, unit=l.unit, due_date=l.due_date) for l in view.baseline.lines]))
