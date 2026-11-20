"""OFF-04.6 shared test support: the ten Quality forms with SYNTHETIC grants, SYNTHETIC bobbins and valid synthetic content generated from the published seed definitions.
No industrial data, no real user, no real key."""
import json
import pathlib
from uuid import UUID

from tests import off045b06b_support as S

BACKEND = pathlib.Path(__file__).resolve().parents[1]
FORMS = ("VINTO-P1-18", "VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-22", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-26", "VINTO-P1-27", "VINTO-P1-28")
BY_MACHINE = ("VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27")
BY_BOBBIN = ("VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28")
SNAPSHOT = S.SNAPSHOT
MACHINE = "MP1"
BOBBIN_A = {"synthetic": True, "bobbin_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "machine_code": "MP1", "bobbin_code": "B-0001-SINT", "work_order": "OT-SINT-1", "line_code": "L1",
            "pv_reference": "PV-SINT-1", "article_code": "ART-SINT-1", "article_description": "Artículo sintético 1", "shift_code": "T1", "operating_date": "2026-11-19"}
BOBBIN_B = {**BOBBIN_A, "bobbin_id": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", "bobbin_code": "B-0002-SINT"}
BOBBIN_MP3 = {**BOBBIN_A, "bobbin_id": "cccccccc-cccc-4ccc-8ccc-cccccccccccc", "machine_code": "MP3", "bobbin_code": "B-0003-SINT"}
BOBBINS = [BOBBIN_A, BOBBIN_B, BOBBIN_MP3]


def seed(form_code: str) -> dict:
    return json.loads((BACKEND / "seed_data" / "forms" / f"{form_code}.json").read_text(encoding="utf-8"))


def version(form_code: str) -> int:
    return seed(form_code)["version_number"]


def grants_all(user_id, machine=MACHINE):
    return [{"user_id": str(user_id), "machine_code": machine, "form_code": f, "form_version": version(f), "synthetic": True, "scope_snapshot_id": str(SNAPSHOT),
             "context_version": S.CONTEXT} for f in FORMS]


OVERRIDES = {
    "VINTO-P1-26": ({"masa_humeda": "200", "masa_seca": "50"}, {"porcentaje_cantidad_de_seco": "25.00"}),
    "VINTO-P1-24": ({"resistencia_longitudinal_humeda_centro": "1.00", "resistencia_longitudinal_humeda_medio": "2.00", "resistencia_longitudinal_humeda_extremo": "4.00",
                     "resistencia_transversal_humeda_centro": "3.00", "resistencia_transversal_humeda_medio": "3.00", "resistencia_transversal_humeda_extremo": "3.00"},
                    {"promedio_longitudinal_humedo": "2.33", "promedio_transversal_humedo": "3.00"}),
    "VINTO-P1-25": ({"resistencia_longitudinal_centro_kgf": "1.00", "resistencia_longitudinal_medio_kgf": "2.00", "resistencia_longitudinal_extremo_kgf": "4.00",
                     "resistencia_longitudinal_humeda_centro_kgf": "3.00", "resistencia_longitudinal_humeda_medio_kgf": "3.00", "resistencia_longitudinal_humeda_extremo_kgf": "3.00", "n_cortes": "3"},
                    {"promedio_resistencia_longitudinal_kgf": "2.33", "promedio_resistencia_longitudinal_humeda_kgf": "3.00"}),
    "VINTO-P1-21": ({"gramaje_01": "10.00", "peso_seco_01": "5.00", "humedad_01": "6.00", "gramaje_02": "20.00", "peso_seco_02": "7.00", "humedad_02": "8.00"},
                    {"promedio_gramaje": "15.00", "promedio_peso_seco": "6.00", "promedio_humedad": "7.00", "posiciones_utilizadas": "2"}),
}


def valid_values(form_code: str, bobbin_code: str = "B-0001-SINT") -> tuple[dict, dict]:
    """(values the device would send, server calculations expected) built from the published seed: every editable field with a valid synthetic value."""
    s = seed(form_code)
    values = {}
    for f in s["fields"]:
        if f["source"] != "manual":
            continue
        if form_code == "VINTO-P1-21" and f["key"][-2:].isdigit():
            continue            # profile table: only the two positions set below (a position is complete with its three values)
        if f.get("options"):
            values[f["key"]] = f["options"][0]["option_key"]
        elif f["value_type"] == "decimal":
            values[f["key"]] = "1.50"
        elif f["value_type"] == "integer":
            values[f["key"]] = "3"
        elif f["value_type"] == "time":
            values[f["key"]] = "10:30"
        elif f["value_type"] == "date":
            values[f["key"]] = "2026-11-19"
        elif f["value_type"] == "boolean":
            values[f["key"]] = True
        else:
            values[f["key"]] = "ensayo sintético"
        if f["key"] == "numero_de_bobina":
            values[f["key"]] = bobbin_code
    over, calc = OVERRIDES.get(form_code, ({}, {}))
    values.update(over)
    return values, dict(calc)


def manual_keys(form_code: str) -> list[str]:
    return [f["key"] for f in seed(form_code)["fields"] if f["source"] == "manual"]


def calculated_keys(form_code: str) -> list[str]:
    return [f["key"] for f in seed(form_code)["fields"] if f["source"] == "calculated"]


def required_keys(form_code: str) -> list[str]:
    return [f["key"] for f in seed(form_code)["fields"] if f["source"] == "manual" and f["required"]]
