from __future__ import annotations

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PvOption(StrictModel):
    pv_reference: str
    eligible_mothers: int = Field(ge=0)


class ProductOption(StrictModel):
    article_id: UUID
    code: str
    description: str = ""


class MachineSnapshot(StrictModel):
    code: str
    name: str


class WorkOrderSnapshot(StrictModel):
    id: UUID
    number: str


class OperatorSnapshot(StrictModel):
    user_id: UUID
    display_name: str


class MotherOption(StrictModel):
    mother_capture_id: UUID
    mother_bobbin_id: UUID | None
    mother_label: str
    pv_reference: str
    article_id: UUID
    article_code: str
    article_description: str = ""
    machine: MachineSnapshot
    work_order: WorkOrderSnapshot
    operating_date: date
    destination: str
    formato_1: str
    formato_2: str | None
    formato_3: str | None
    diametro: str
    tubete: str
    ayudante: str | None
    operator: OperatorSnapshot | None


class ChildOption(StrictModel):
    bobbin_id: UUID
    mother_capture_id: UUID
    position: int = Field(ge=1, le=22)
    weight_kg: str
    quality_status: Literal["released"] = "released"


class PackageChildInput(StrictModel):
    package_slot: Literal["A", "B", "C", "D", "E"]
    child_bobbin_id: UUID


class PackageInput(StrictModel):
    mother_capture_id: UUID
    children: list[PackageChildInput] = Field(min_length=1, max_length=5)

    @model_validator(mode="after")
    def validate_slots(self) -> "PackageInput":
        slots = [child.package_slot for child in self.children]
        ids = [child.child_bobbin_id for child in self.children]
        if "A" not in slots:
            raise ValueError("La Cría A es obligatoria.")
        if len(set(slots)) != len(slots):
            raise ValueError("No se puede repetir una posición A–E.")
        if len(set(ids)) != len(ids):
            raise ValueError("No se puede repetir una cría dentro del paquete.")
        return self


class PackageChildOut(StrictModel):
    bobbin_id: UUID
    package_slot: Literal["A", "B", "C", "D", "E"]
    position: int
    weight_kg: str


class PackageOut(StrictModel):
    id: UUID
    package_number: int
    mother_capture_id: UUID
    mother_label_snapshot: str
    mother: MotherOption
    children: list[PackageChildOut]


class DraftSummaryOut(StrictModel):
    id: UUID
    created_at: datetime
    pv_reference: str
    article_code: str
    machine_code: str | None
    package_count: int


class ArticleSnapshot(StrictModel):
    id: UUID
    code: str
    description: str = ""


class DraftOut(StrictModel):
    id: UUID
    status: Literal["draft"] = "draft"
    created_at: datetime
    pv_reference: str
    article: ArticleSnapshot
    truck_number: str
    order_number: str
    observations: str
    packages: list[PackageOut]


class PreviewMessage(StrictModel):
    code: str
    message: str


class PreviewOut(StrictModel):
    valid: bool
    package_count: int
    child_count: int
    warnings: list[PreviewMessage]
    blocking_errors: list[PreviewMessage]


class ClassificationActor(StrictModel):
    id: UUID
    display_name: str


class ClassificationOut(StrictModel):
    work_order_id: UUID
    classification: Literal["production_confirmed", "qa"] | None
    sequence_no: int | None
    recorded_at: datetime | None
    reason: str | None
    recorded_by: ClassificationActor | None


class WorkOrderOption(StrictModel):
    id: UUID
    number: str
    status: Literal["published", "in_progress", "closed"]
    machine_code: str


class CreateDraftInput(StrictModel):
    pv_reference: str = Field(min_length=1, max_length=100)
    article_id: UUID
    truck_number: str = Field(default="", max_length=80)
    order_number: str = Field(default="", max_length=80)
    observations: str = Field(default="", max_length=2000)


class UpdateDraftInput(StrictModel):
    truck_number: str = Field(default="", max_length=80)
    order_number: str = Field(default="", max_length=80)
    observations: str = Field(default="", max_length=2000)


class ClassificationInput(StrictModel):
    classification: Literal["production_confirmed", "qa"]
    reason: str = Field(min_length=10, max_length=300)


class AnnulInput(StrictModel):
    reason: str = Field(min_length=10, max_length=300)
