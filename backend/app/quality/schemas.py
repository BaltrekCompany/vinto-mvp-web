"""Esquemas HTTP de la bandeja de Calidad. Salida cerrada: sin created_by/updated_by, dispositivo, auditoría ni ids internos innecesarios."""

from datetime import date, datetime, time
from uuid import UUID

from pydantic import BaseModel

from app.capture_schemas import ArticleOut, CodeNameOut, WorkOrderRefOut
from app.quality.service import QualityBobbinView


class InboxBobbinOut(BaseModel):
    id: UUID
    code: str
    machine: CodeNameOut
    management_start_year: int
    sequence_number: int
    start_time: time
    end_time: time
    diameter_mm: str  # decimales como texto para no perder precisión
    weight_kg: str
    grammage_g_m2: str | None  # None: el producto no tiene gramaje (no es un error)
    number_of_cuts: str
    notes: str | None


class InboxLineOut(BaseModel):
    id: UUID
    line_code: str
    pv_reference: str
    article: ArticleOut


class InboxProductionOut(BaseModel):
    capture_id: UUID
    captured_at: datetime
    operating_date: date
    shift: CodeNameOut
    work_order: WorkOrderRefOut
    line: InboxLineOut


class InboxQualityOut(BaseModel):
    status: str


class QualityBobbinOut(BaseModel):
    bobbin: InboxBobbinOut
    production: InboxProductionOut
    quality: InboxQualityOut


def quality_bobbin_out(v: QualityBobbinView) -> QualityBobbinOut:
    return QualityBobbinOut(
        bobbin=InboxBobbinOut(
            id=v.bobbin_id, code=v.code, machine=CodeNameOut(code=v.machine_code, name=v.machine_name), management_start_year=v.management_start_year,
            sequence_number=v.sequence_number, start_time=v.start_time, end_time=v.end_time, diameter_mm=v.diameter_mm, weight_kg=v.weight_kg,
            grammage_g_m2=v.grammage_g_m2, number_of_cuts=v.number_of_cuts, notes=v.notes),
        production=InboxProductionOut(
            capture_id=v.capture_id, captured_at=v.captured_at, operating_date=v.operating_date, shift=CodeNameOut(code=v.shift_code, name=v.shift_name),
            work_order=WorkOrderRefOut(id=v.work_order_id, number=v.work_order_number),
            line=InboxLineOut(id=v.line_id, line_code=v.line_code, pv_reference=v.pv_reference,
                              article=ArticleOut(code=v.article_code, description=v.article_description))),
        quality=InboxQualityOut(status=v.quality_status))
