"""Informe de SOLO LECTURA de un bundle candidato frente al bundle aprobado (M4-B1). No accede a PostgreSQL, no escribe archivos y no promueve nada.

  python candidate_report.py <directorio-del-bundle-candidato> [--json]

Valida el candidato con `load_bundle` (manifest, SHA-256, conteos, referencias) y compara su contenido con `backend/seed_data`: qué coincide con lo aprobado, qué es
candidato pendiente de aprobación, qué inconsistencias hay y qué falta. No edita ni «arregla» datos.
"""

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

from app.seed.bundle import BUNDLE_DIR, BundleError, load_bundle

REQUIRED_FORMS_FOR_REBOBINADO = ("VINTO-P1-10", "VINTO-P1-29")


def build_report(candidate_dir: Path, approved_dir: Path = BUNDLE_DIR) -> dict:
    candidate, approved = load_bundle(candidate_dir), load_bundle(approved_dir)
    scope = candidate.manifest.get("scope", {})
    sectors_of = {m["code"]: m["sector"] for m in candidate.machines}
    approved_sectors = {s["code"] for s in approved.sectors}
    new_sectors = sorted({s["code"] for s in candidate.sectors} - approved_sectors)

    # --- coincide con lo aprobado (el sector ya aprobado debe ser idéntico dentro del candidato)
    def only(items, key, sector_values):
        return [i for i in items if i[key] in sector_values]
    approved_machines = {m["code"] for m in approved.machines}
    identical = {
        "sectores_aprobados": [s for s in candidate.sectors if s["code"] in approved_sectors] == list(approved.sectors),
        "maquinas_aprobadas": only(candidate.machines, "code", approved_machines) == list(approved.machines),
        "horarios_aprobados": [s for s in candidate.schedules if s["sector"] in approved_sectors] == list(approved.schedules),
        "formularios": list(candidate.forms) == list(approved.forms),
        "relaciones_articulo_maquina_aprobadas": only(candidate.article_machines, "machine_code", approved_machines) == list(approved.article_machines),
        "perfiles": candidate.profiles == approved.profiles,
        "unidades": candidate.units == approved.units,
    }

    # --- datos candidatos pendientes de aprobación
    candidate_machines = [m for m in candidate.machines if m["sector"] in new_sectors]
    machine_articles = defaultdict(set)
    for link in candidate.article_machines:
        machine_articles[link["machine_code"]].add(link["article_code"])
    shifts = [s for s in candidate.schedules if s["sector"] in new_sectors]
    pending = {
        "sectores": new_sectors,
        "maquinas": [{"codigo": m["code"], "nombre": m["name"], "sector": m["sector"], "nombre_igual_al_codigo": m["name"] == m["code"],
                      "articulos": len(machine_articles[m["code"]])} for m in candidate_machines],
        "horarios": [{"turno": s["shift"], "sector": s["sector"], "inicio": s["starts_at"], "fin": s["ends_at"], "zona": s["timezone"], "vigente_desde": s["valid_from"],
                      "vigente_hasta": s["valid_to"]} for s in shifts],
        "articulos_relacionados_solo_con_candidatas": len({a for m in candidate_machines for a in machine_articles[m["code"]]} -
                                                         {a for m in approved_machines for a in machine_articles[m]}),
    }

    # --- inconsistencias / alertas
    article_codes = {a["code"] for a in candidate.articles}
    sectors_per_article = defaultdict(set)
    for link in candidate.article_machines:
        sectors_per_article[link["article_code"]].add(sectors_of[link["machine_code"]])
    form_machines = {f["code"]: sorted(f["machines"]) for f in candidate.forms}
    rebobinado_machine_codes = {m["code"] for m in candidate_machines}
    conflicts = {
        "relaciones_con_articulo_inexistente": sorted(l["article_code"] for l in candidate.article_machines if l["article_code"] not in article_codes),
        "articulos_sin_maquina": sorted(article_codes - set(sectors_per_article)),
        "articulos_en_mas_de_un_sector": len([a for a, s in sectors_per_article.items() if len(s) > 1]),
        "maquinas_candidatas_sin_articulos": sorted(c for c in rebobinado_machine_codes if not machine_articles[c]),
        "maquinas_con_nombre_derivado_del_codigo": sorted(m["code"] for m in candidate_machines if m["name"] == m["code"]),
        "formularios_vinculados_a_maquinas_candidatas": sorted(c for c, ms in form_machines.items() if rebobinado_machine_codes & set(ms)),
        "unidades_con_etiqueta_igual_al_codigo": sorted(u["code"] for u in candidate.units if u["label"] == u["code"]),
        "turnos_con_codigo_compartido_y_horas_distintas": sorted({s["shift"] for s in shifts
                                                                  for o in candidate.schedules if o["shift"] == s["shift"] and o["sector"] != s["sector"]
                                                                  and (o["starts_at"], o["ends_at"]) != (s["starts_at"], s["ends_at"])}),
        "advertencias_del_manifest": sorted(w["code"] for w in candidate.manifest.get("warnings", []) if w.get("severity") == "warning"),
    }

    # --- datos faltantes (no están en el bundle)
    form_codes = {f["code"] for f in candidate.forms}
    missing = {
        "formularios_rebobinado_ausentes": [c for c in REQUIRED_FORMS_FOR_REBOBINADO if c not in form_codes],
        "vinculos_formulario_maquina_de_rebobinado": 0 if not conflicts["formularios_vinculados_a_maquinas_candidatas"] else len(conflicts["formularios_vinculados_a_maquinas_candidatas"]),
        "pesos_nominales": candidate.manifest.get("counts", {}).get("articles_with_nominal_weight", 0) == 0,
    }
    return {
        "candidato": bool(scope.get("candidate")), "integridad": "OK (manifest, SHA-256, conteos y referencias)",
        "conteos": candidate.manifest.get("counts", {}), "coincide_con_lo_aprobado": identical, "pendiente_de_aprobacion": pending,
        "conflictos": conflicts, "faltantes": missing, "unidades_de_articulos": dict(Counter(a["version"]["unit"] for a in candidate.articles)),
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Informe de solo lectura de un bundle candidato (no escribe, no importa, no promueve)")
    parser.add_argument("bundle", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        report = build_report(args.bundle)
    except BundleError as error:
        print(f"Bundle inválido: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
