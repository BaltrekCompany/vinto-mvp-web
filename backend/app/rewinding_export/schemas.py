"""Contratos HTTP cerrados del módulo RBE-04."""
from datetime import datetime
from typing import Literal
from uuid import UUID
from pydantic import BaseModel, ConfigDict, Field

class DraftCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pv_reference: str = Field(min_length=1, max_length=100)
    article_id: UUID
    truck_number: str = Field(default="", max_length=80)
    order_number: str = Field(default="", max_length=80)
    observations: str = Field(default="", max_length=2000)

class DraftHeaderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    truck_number: str = Field(default="", max_length=80)
    order_number: str = Field(default="", max_length=80)
    observations: str = Field(default="", max_length=2000)

class PackageCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mother_capture_id: UUID

class PackageWithChildrenIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mother_capture_id: UUID
    children: list["ChildCreateIn"] = Field(min_length=1, max_length=5)

class ChildCreateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    child_bobbin_id: UUID
    package_slot: Literal["A", "B", "C", "D", "E"]

class LogicalRemoveIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(default="RBE draft edit", min_length=1, max_length=300)

class ClassificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    classification: Literal["production_confirmed", "qa"]
    reason: str = Field(min_length=10, max_length=300)

class GenerateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    idempotency_key: UUID


class AnnulIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: str = Field(min_length=10, max_length=300)

class DraftCreatedOut(BaseModel):
    id: UUID

class PackageCreatedOut(BaseModel):
    id: UUID

class ChildCreatedOut(BaseModel):
    id: UUID

class ClassificationOut(BaseModel):
    id: UUID

class HistoryItemOut(BaseModel):
    id: UUID
    status: str
    pv_reference: str
    article_code_snapshot: str
    truck_number: str
    order_number: str
    created_at: datetime
    generated_at: datetime | None
    annulled_at: datetime | None
    machine_code: str | None

class ClassifiableWorkOrderOut(BaseModel):
    id: UUID
    number: str
    status: str
    machine_code: str
    machine_name: str
    classification: str | None
    sequence_no: int | None
    recorded_at: datetime | None

class AnnulOut(BaseModel):
    report_id: UUID
    released_reservations: int
