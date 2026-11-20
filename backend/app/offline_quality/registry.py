"""The ten Quality forms of OFF-04.6 as ONE registry, derived at call time from the policy the ONLINE routes already use (never copied): a form added to or removed from an
online route changes this registry, and the contract test then says so."""
from __future__ import annotations

from dataclasses import dataclass

from app.authz.policies import POLICIES, Operation

MACHINE = "machine"
BOBBIN = "bobbin"
# The batch, in numeric order. The kind of each form is decided by the online policy (machine route vs bobbin route), not by this tuple.
BATCH_FORMS = ("VINTO-P1-18", "VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-22", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-26", "VINTO-P1-27", "VINTO-P1-28")


@dataclass(frozen=True)
class FormSpec:
    code: str
    kind: str                # "machine" | "bobbin"
    operation: Operation     # the effective-authorization operation of the online route


def machine_forms() -> frozenset:
    return frozenset(POLICIES[Operation.QUALITY_MACHINE_CAPTURE].admitted())


def bobbin_forms() -> frozenset:
    return frozenset(POLICIES[Operation.QUALITY_BOBBIN_CAPTURE].admitted())


def spec_for(form_code: str) -> FormSpec | None:
    """None for a form that no online Quality route admits (never an implicit authorisation)."""
    if form_code in machine_forms():
        return FormSpec(form_code, MACHINE, Operation.QUALITY_MACHINE_CAPTURE)
    if form_code in bobbin_forms():
        return FormSpec(form_code, BOBBIN, Operation.QUALITY_BOBBIN_CAPTURE)
    return None


def operation_for(form_code: str) -> Operation | None:
    spec = spec_for(form_code)
    return spec.operation if spec else None


def all_specs() -> list[FormSpec]:
    return [s for s in (spec_for(code) for code in BATCH_FORMS) if s is not None]
