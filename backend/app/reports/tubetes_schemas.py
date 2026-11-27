"""HTTP response models for the Tubetes Utilizados report."""

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


MachineCode = Literal["MP1", "MP3"]


class TubeteUsageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str
    usage_count: int = Field(ge=1)
    dates: list[date]


class MachineTubetesOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    machine: MachineCode
    usage_total: int = Field(ge=0)
    records_without_code: int = Field(ge=0)
    tubetes: list[TubeteUsageOut]


class TubetesReportOut(BaseModel):
    model_config = ConfigDict(extra="forbid")

    generated_at: datetime
    source_form: Literal["VINTO-P1-03"] = "VINTO-P1-03"
    date_basis: Literal["operating_date"] = "operating_date"
    timezone: Literal["America/La_Paz"] = "America/La_Paz"
    machines: list[MachineTubetesOut]
