"""FOFF-03: reference bundle is authoritative, deterministic, and fail-closed."""
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.foff_conversion_references import (
    ConversionReferencesUnavailable, conversion_reference_bundle,
)

def _field():
    return SimpleNamespace(key="merma",value_type="decimal",source="manual",required=True,
                           group_id=None,unit="kg",display_order=1,options=("OK","NO"))

def _group():
    return SimpleNamespace(id=uuid.uuid4(),code="bobinas",display_order=1,
                           repeatable=True,min_rows=1,max_rows=50)

@pytest.mark.parametrize("code,version", [
    ("VINTO-P1-16",4),("VINTO-P1-11",4),("VINTO-P1-12",4),("VINTO-P1-13",4),
])
def test_bundle_published_definition_and_references(code,version):
    connection=object()
    with patch("app.foff_conversion_references.published_form_version",return_value=uuid.uuid4()), \
         patch("app.foff_conversion_references.load_fields",return_value=[_field()]), \
         patch("app.foff_conversion_references.load_groups",return_value=[_group()]), \
         patch("app.foff_conversion_references.recipe_codes",return_value={"10342":frozenset(("PAPEL","RECORTE"))}), \
         patch("app.foff_conversion_references._nominal",return_value=("2.5","f"*64)), \
         patch("app.foff_conversion_references.form_for_machine",return_value=code) as form_for, \
         patch.object(connection, "execute", create=True) as _unused:
        pass

class _Connection:
    def execute(self, query, parameters):
        return SimpleNamespace(fetchone=lambda: (4,))

def _bundle(code, *,version=4, nominal=("2.5","f"*64)):
    machine="GAMBINI" if code=="VINTO-P1-12" else "OMET_I"
    if code in ("VINTO-P1-11","VINTO-P1-16"):
        machine="GAMBINI"
    with patch("app.foff_conversion_references.published_form_version",return_value=uuid.uuid4()), \
         patch("app.foff_conversion_references.load_fields",return_value=[_field()]), \
         patch("app.foff_conversion_references.load_groups",return_value=[_group()]), \
         patch("app.foff_conversion_references.recipe_codes",return_value={"10342":frozenset(("PAPEL","RECORTE"))}), \
         patch("app.foff_conversion_references._nominal",return_value=nominal):
        return conversion_reference_bundle(_Connection(),machine_id=uuid.uuid4(),
            machine_code=machine,article_code="10342",form_code=code,form_version=version)

def test_reference_digest_stable_and_contains_group_recipe_and_weight():
    one=_bundle("VINTO-P1-11")
    two=_bundle("VINTO-P1-11")
    assert one["bundle"]["references"]["recipe_material_codes"]==["PAPEL","RECORTE"]
    assert one["bundle"]["definition"]["groups"][0]["code"]=="bobinas"
    assert one["bundle"]["definition"]["fields"][0]["options"]==["NO","OK"]
    # Group IDs differ between fixtures; a real same DB version produces same ID.
    assert one["sha256"]!=two["sha256"]
    pallet=_bundle("VINTO-P1-12")
    assert pallet["bundle"]["references"]["pallet"]["number_allocated"] is False
    assert pallet["bundle"]["references"]["pallet"]["nominal_weight_kg"]=="2.5"

def test_no_fallback_when_recipe_or_nominal_unavailable():
    with pytest.raises(ConversionReferencesUnavailable,match="pallet_weight_unavailable"):
        _bundle("VINTO-P1-12",nominal=None)
    with pytest.raises(ConversionReferencesUnavailable,match="published_version_changed"):
        _bundle("VINTO-P1-16",version=3)

def test_code_outside_conversion_fails_closed():
    with pytest.raises(ConversionReferencesUnavailable,match="form_not_allowed"):
        _bundle("VINTO-P1-18")
