"""FOFF-03 — authoritative read-only reference bundle for Conversion.

Never invents a recipe or pallet number. Called only after the user, machine,
form and assignment have been authorized by the calling service.
This bundle is NOT a CAPTURE authority and must not enable an offline editor.
"""
import hashlib

from app.capture_service import load_fields, load_groups, published_form_version
from app.foff_conversion_preparation import CONVERSION_CODES
from app.p111_recipe_policy import recipe_codes
from app.production_pallets import _nominal, form_for_machine
from app.quality.offline_capture_scope import _canonical


class ConversionReferencesUnavailable(ValueError):
    pass


def _fields(connection, form_version_id):
    fields = load_fields(connection, form_version_id, allow_groups=True)
    groups = load_groups(connection, form_version_id)
    return {
        "fields": [
            {
                "key": f.key,
                "value_type": f.value_type,
                "source": f.source,
                "required": bool(f.required),
                "group_id": str(f.group_id) if f.group_id else None,
                "unit": f.unit,
                "display_order": f.display_order,
                "options": sorted(f.options),
            }
            for f in fields
        ],
        "groups": [
            {
                "id": str(g.id),
                "code": g.code,
                "display_order": g.display_order,
                "repeatable": bool(g.repeatable),
                "min_rows": g.min_rows,
                "max_rows": g.max_rows,
            }
            for g in groups
        ],
    }


def conversion_reference_bundle(connection, *, machine_id, machine_code,
                                article_code, form_code, form_version):
    if form_code not in CONVERSION_CODES:
        raise ConversionReferencesUnavailable("form_not_allowed")
    version_id = published_form_version(connection, form_code, machine_id)
    row = connection.execute(
        "SELECT version_number FROM vinto_config.form_version WHERE id=%s",
        (version_id,),
    ).fetchone()
    if not row or row[0] != form_version:
        raise ConversionReferencesUnavailable("published_version_changed")
    definition = _fields(connection, version_id)
    references = {"recipe_material_codes": [], "pallet": None}
    if form_code in {"VINTO-P1-11", "VINTO-P1-13"} and form_version >= 3:
        materials = recipe_codes().get(article_code)
        if not materials:
            raise ConversionReferencesUnavailable("recipe_unavailable")
        references["recipe_material_codes"] = sorted(materials)
    if form_code in {"VINTO-P1-12", "VINTO-P1-13"}:
        if form_for_machine(machine_code) != form_code:
            raise ConversionReferencesUnavailable("form_machine_mismatch")
        if (form_code == "VINTO-P1-12" and form_version >= 4) or (
            form_code == "VINTO-P1-13" and form_version >= 3
        ):
            nominal = _nominal(connection, article_code)
            if nominal is None:
                raise ConversionReferencesUnavailable("pallet_weight_unavailable")
            references["pallet"] = {
                "nominal_weight_kg": str(nominal[0]),
                "source_sha256": str(nominal[1]),
                "number_allocated": False,
            }
    bundle = {
        "schema": "vinto.foff.conversion.references.v1",
        "machine_code": machine_code,
        "form_code": form_code,
        "form_version": form_version,
        "article_code": article_code,
        "definition": definition,
        "references": references,
    }
    return {"bundle": bundle, "sha256": hashlib.sha256(_canonical(bundle)).hexdigest()}
