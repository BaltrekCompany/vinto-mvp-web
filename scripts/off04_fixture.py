#!/usr/bin/env python3
"""OFF-04.1 synthetic LABORATORY definition (every editable field type), signed by the REAL signer.

Everything is synthetic: identities, grants, keys and the form itself ("SINTÉTICO · ..."). The
lab editor refuses any definition that is not explicitly marked synthetic, so a real published
package can never be edited by it. Also emits an ordinary (non-lab) package to prove that refusal.
"""
import hashlib
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from off03b3_fixture import DEVICE_ID, USER_ID, signer, synthetic_quality_package, sign_for_device  # noqa: E402
from off03c4_fixture import OTHER_USER_ID, pair, scope, uid  # noqa: E402
from app.offline_scope.signing import (  # noqa: E402
    ISSUER, PACKAGE_AUDIENCE, PACKAGE_SCHEMA, canonical_payload, sign_quality_package,
)

FORM = "VINTO-P1-26"
NAME = "SINTÉTICO · Laboratorio de Calidad (no homologado)"
NOTE = "Synthetic QA-only definition; no industrial captures."


def field(key, label, vtype, order, required, *, source="manual", options=None, rule=None, unit=None):
    return {"key": key, "label": label, "description": "", "value_type": vtype, "source": source,
            "required": required, "unit": unit, "classification": None, "proposal": None,
            "needs_validation": False, "display_order": order, "calculation_rule": rule,
            "options": options or []}


def definition(version):
    suffix = "" if version == 1 else f" v{version}"
    return {
        "form_code": FORM, "form_name": NAME, "form_version": version, "area": "quality",
        "source_definition_checksum": hashlib.sha256(f"off04:{FORM}:{version}".encode()).hexdigest(),
        "published_at": "2026-11-18T10:00:00+00:00", "groups": [],
        "fields": [
            field("numero_de_cuba", "Número de cuba" + suffix, "text", 1, True),
            field("tipo_pasta", "Tipo de pasta", "text", 2, True,
                  options=[{"option_key": "estandar", "label": "Estándar", "display_order": 1},
                           {"option_key": "reforzada", "label": "Reforzada", "display_order": 2}]),
            field("masa_humeda_g", "Masa húmeda", "decimal", 3, True, unit="g"),
            field("masa_seca_g", "Masa seca", "decimal", 4, True, unit="g"),
            field("consistencia_pct", "Consistencia", "decimal", 5, False, source="calculated", unit="%",
                  rule="percent_two_decimals_half_up"),
            field("cantidad_muestras", "Cantidad de muestras", "integer", 6, True),
            field("fecha_muestreo", "Fecha de muestreo", "date", 7, True),
            field("hora_muestreo", "Hora de muestreo", "time", 8, False),
            field("muestra_valida", "Muestra válida", "boolean", 9, True),
            field("observaciones", "Observaciones", "textarea", 10, False),
        ],
        "calculated_rules": {"consistencia_pct": {"method": "percent_two_decimals_half_up", "numerator": "masa_seca_g",
                                                   "denominator": "masa_humeda_g", "denominator_zero": "omit_calculation"}},
        "option_dependencies": [], "recipe_bundle_included": False, "capture_eligible": False, "note": NOTE,
    }


FORM_P122 = "VINTO-P1-22"
NAME_P122 = "SINTÉTICO · Grado de refinación Schopper (candidato OFF-04.5A, no homologado)"


def definition_p122(version):
    """Synthetic mirror of the published P1-22 seed contract (5 manual fields, no calculated field, no option lists).

    Field keys, types and required flags follow backend/seed_data/forms/VINTO-P1-22.json. Ranges, units, precision and
    cross-field rules are NOT in the seed and are deliberately not invented: the form is NOT industrially homologated.
    """
    return {
        "form_code": FORM_P122, "form_name": NAME_P122, "form_version": version, "area": "quality",
        "source_definition_checksum": hashlib.sha256(f"off045a:{FORM_P122}:{version}".encode()).hexdigest(),
        "published_at": "2026-11-18T10:00:00+00:00", "groups": [],
        "fields": [
            field("numero_de_cuba", "Número de cuba", "text", 1, True),
            field("masa_humeda", "Masa húmeda", "decimal", 2, True),
            field("grado_de_refinacion_sr", "Grado de refinación (°SR)", "decimal", 3, True),
            field("amperaje", "Amperaje", "decimal", 4, True),
            field("observacion", "Observación", "textarea", 5, False),
        ],
        "calculated_rules": {}, "option_dependencies": [], "recipe_bundle_included": False, "capture_eligible": False, "note": NOTE,
    }


def lab_package(scope_envelope, version, form=FORM, make_definition=None):
    sp = scope_envelope["payload"]
    item = next(x for x in sp["form_scopes"] if x["form_code"] == form)
    d = (make_definition or definition)(version)
    payload = {
        "schema": PACKAGE_SCHEMA, "issuer": ISSUER, "audience": PACKAGE_AUDIENCE,
        "kind": "quality_definition_readiness_only", "captures_enabled": False,
        "package_id": uid("off04-package", sp["snapshot_id"], str(version)),
        "scope_snapshot_id": sp["snapshot_id"], "subject_user_id": sp["subject_user_id"], "device_key": sp["device_key"],
        "machine_code": item["machine_code"], "form_code": form, "form_version": version, "grant_id": item["grant_id"],
        "issued_at": sp["issued_at"], "content_sha256": hashlib.sha256(canonical_payload(d)).hexdigest(), "definition": d,
    }
    return sign_quality_package(payload, signer=signer())


def lab_package_p122(scope_envelope, version=1):
    return lab_package(scope_envelope, version, FORM_P122, definition_p122)


def build():
    s1 = scope("off04-v1", "2026-11-18T12:00:00Z", [pair("MP1", FORM, 1)])
    s2 = scope("off04-v2", "2026-11-18T13:00:00Z", [pair("MP1", FORM, 2)])
    real = sign_for_device(DEVICE_ID)           # ordinary (non-lab) P1-18 package definition
    return {"identity": {"ownerId": USER_ID, "deviceKey": DEVICE_ID},
            "other_identity": {"ownerId": OTHER_USER_ID, "deviceKey": DEVICE_ID},
            "scope": s1, "package": lab_package(s1, 1), "scope_v2": s2, "package_v2": lab_package(s2, 2),
            "non_lab_scope": real, "non_lab_package": synthetic_quality_package(real)}


if __name__ == "__main__":
    path = os.environ.get("OFF04_FIXTURE_JSON")
    if not path:
        raise SystemExit("OFF04_FIXTURE_JSON required")
    Path(path).write_text(json.dumps(build(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print("OFF04_PYTHON_SIGNED_LAB_FIXTURE=PASS", flush=True)
