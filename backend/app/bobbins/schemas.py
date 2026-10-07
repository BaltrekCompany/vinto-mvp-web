"""Esquemas HTTP de producción de bobinas F3. El cliente solo envía capture_id, assignment_id, device_key y los seis
valores manuales; cualquier otro campo (fecha, turno, máquina, código, gramaje...) se rechaza (extra="forbid")."""

from datetime import datetime, time
from typing import Any
from uuid import UUID

from pydantic import UUID4, BaseModel, ConfigDict

from app.bobbins.service import BobbinResult
from app.capture_schemas import ArticleOut, CaptureOut, CodeNameOut, capture_out


class BobbinValuesIn(BaseModel):
    """Valores crudos (Any, sin coerción de Pydantic): la única autoridad del tipo funcional es la definición publicada del
    formulario aplicada por capture_service.validate_values. Aquí solo se exige la estructura cerrada y los campos obligatorios."""
    model_config = ConfigDict(extra="forbid")

    hora_inicio: Any
    hora_fin: Any
    diametro: Any
    peso_kg: Any
    numero_de_cortes: Any
    observaciones: Any = None


class BobbinIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capture_id: UUID4
    assignment_id: UUID
    device_key: UUID
    values: BobbinValuesIn


class BobbinOut(BaseModel):
    id: UUID
    code: str
    capture_id: UUID
    machine: CodeNameOut
    management_start_year: int
    sequence_number: int
    start_time: time
    end_time: time
    diameter_mm: str  # decimales como texto para no perder precisión
    weight_kg: str
    grammage_g_m2: str | None
    number_of_cuts: str
    notes: str | None
    article: ArticleOut
    quality_status: str
    created_at: datetime


class BobbinResultOut(BaseModel):
    created: bool
    already_submitted: bool
    bobbin: BobbinOut
    capture: CaptureOut


def bobbin_out(v) -> BobbinOut:
    return BobbinOut(
        id=v.id, code=v.code, capture_id=v.capture_id, machine=CodeNameOut(code=v.machine_code, name=v.machine_name),
        management_start_year=v.management_start_year, sequence_number=v.sequence_number, start_time=v.start_time, end_time=v.end_time,
        diameter_mm=v.diameter_mm, weight_kg=v.weight_kg, grammage_g_m2=v.grammage_g_m2, number_of_cuts=v.number_of_cuts, notes=v.notes,
        article=ArticleOut(code=v.article_code, description=v.article_description), quality_status=v.quality_status, created_at=v.created_at)


def result_out(result: BobbinResult) -> BobbinResultOut:
    return BobbinResultOut(created=result.created, already_submitted=result.already_submitted, bobbin=bobbin_out(result.bobbin),
                           capture=capture_out(result.capture))
