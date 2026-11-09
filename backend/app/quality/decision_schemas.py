"""Contrato cerrado de liberacion/rechazo de una unidad de bobina.

Rechazado/Reutilizable son TIPOS de rechazo, no estados adicionales de quality_release.
El estado de persistencia es siempre pending/released/rejected.
"""
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, UUID4, model_validator

RejectionType = Literal["rechazado", "reutilizable"]
RejectionClass = Literal["dimensiones", "formato", "defecto_visible", "humedad", "propiedades_bobina", "otros"]


class QualityDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    decision_id: UUID4
    action: Literal["release", "reject"]
    rejection_type: RejectionType | None = None
    classification: RejectionClass | None = None
    detail: str | None = Field(default=None, max_length=4000)
    corrective_action: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def check_fields(self):
        fields = (self.rejection_type, self.classification, self.detail, self.corrective_action)
        if self.action == "release":
            if any(x is not None for x in fields):
                raise ValueError("Liberar no admite campos de rechazo")
        else:
            if any(x is None for x in fields):
                raise ValueError("El rechazo exige tipo, clasificacion, detalle y accion correctiva")
            if not self.detail.strip() or not self.corrective_action.strip():
                raise ValueError("Detalle y accion correctiva no pueden estar vacios")
        return self


class QualityDecisionOut(BaseModel):
    bobbin_id: UUID
    status: Literal["released", "rejected"]
    already_decided: bool
