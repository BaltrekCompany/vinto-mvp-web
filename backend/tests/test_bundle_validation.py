"""M1-B2-a · Validaciones puras del bundle de referencia (app/seed/bundle.py): códigos, duplicados, referencias, relaciones artículo-máquina, unidades y
horarios (huecos, solapes, cruce de medianoche, vigencias y cambios de vigencia). Sin base de datos: se parte del bundle APROBADO y se le aplican variantes
sintéticas con dataclasses.replace. Los escenarios "futuros" (CONVERSION, REBOBINADO...) son sintéticos y nunca se importan.
"""

import copy
import dataclasses
import unittest
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.seed import bundle as bundle_module
from app.seed.bundle import BundleError, load_bundle
from app.shifts import ScheduleRow, resolve_shift_from_schedules

BUNDLE = load_bundle()
TZ = "America/La_Paz"
BOBINAS_SCHEDULES = tuple(BUNDLE.schedules)  # DIA 07–19, NOCHE 19–07, desde 2026-01-01


def validate(bundle):
    bundle_module._validate_content(bundle)


def variant(**changes):
    return dataclasses.replace(BUNDLE, **changes)


def sch(shift, sector, start, end, valid_from="2026-01-01", valid_to=None, tz=TZ):
    return {"shift": shift, "sector": sector, "starts_at": start, "ends_at": end, "timezone": tz, "valid_from": valid_from, "valid_to": valid_to}


def with_schedules(schedules, extra_shifts=()):
    shifts = list(BUNDLE.shifts) + [s for s in extra_shifts if s["code"] not in {x["code"] for x in BUNDLE.shifts}]
    return variant(schedules=tuple(schedules), shifts=tuple(shifts))


def with_future_sector(code="CONVERSION", name="Conversión", machines=(("GAMBINI", "Gambini"),), schedules=(), shifts=(), articles=(), relations=(), units=()):
    return variant(
        sectors=BUNDLE.sectors + ({"code": code, "name": name},),
        machines=BUNDLE.machines + tuple({"code": c, "name": n, "sector": code} for c, n in machines),
        shifts=BUNDLE.shifts + tuple(s for s in shifts if s["code"] not in {x["code"] for x in BUNDLE.shifts}),
        schedules=BUNDLE.schedules + tuple(schedules), units=BUNDLE.units + tuple(units),
        articles=BUNDLE.articles + tuple(articles), article_machines=BUNDLE.article_machines + tuple(relations))


def new_article(code, unit="KG"):
    template = copy.deepcopy(BUNDLE.articles[0])
    template["code"], template["version"]["unit"] = code, unit
    return template


THREE_SHIFTS = (sch("MANANA", "CONVERSION", "06:00", "14:00"), sch("TARDE", "CONVERSION", "14:00", "22:00"), sch("NOCHE", "CONVERSION", "22:00", "06:00"))
THREE_SHIFT_CODES = ({"code": "MANANA", "name": "Mañana"}, {"code": "TARDE", "name": "Tarde"}, {"code": "NOCHE", "name": "Noche"})


class ApprovedBundleTests(unittest.TestCase):
    def test_the_approved_bundle_still_validates_and_keeps_its_identity(self):
        validate(BUNDLE)
        self.assertEqual(BUNDLE.source_checksum, "fe414660207434a6f7fd5aab0c415c0212efa78e843a79d90a369f32c91d2a13")
        self.assertEqual([(s["shift"], s["starts_at"], s["ends_at"], s["valid_from"], s["valid_to"]) for s in BUNDLE.schedules],
                         [("DIA", "07:00", "19:00", "2026-01-01", None), ("NOCHE", "19:00", "07:00", "2026-01-01", None)])
        self.assertEqual(([s["code"] for s in BUNDLE.sectors], [m["code"] for m in BUNDLE.machines]), (["BOBINAS"], ["MP1", "MP3"]))
        self.assertEqual((len(BUNDLE.articles), len(BUNDLE.article_machines)), (93, 93))

    def test_a_sector_without_schedules_is_allowed_because_it_stays_blocked_by_the_missing_shift(self):
        validate(with_future_sector("REBOBINADO", "Rebobinado", machines=(("COPASA", "Copasa"),)))

    def test_a_complete_future_sector_validates_and_reuses_a_shift_code_with_other_hours(self):
        pen = [new_article("ZZ-0001", "PACK"), new_article("ZZ-0002", "PACK")]
        bundle = with_future_sector(machines=(("GAMBINI", "Gambini"), ("SINCRO_II", "Sincro II")), shifts=THREE_SHIFT_CODES, schedules=THREE_SHIFTS, articles=pen,
                                    relations=({"article_code": "ZZ-0001", "machine_code": "GAMBINI"}, {"article_code": "ZZ-0002", "machine_code": "SINCRO_II"}),
                                    units=({"code": "PACK", "label": "Pack"},))
        validate(bundle)  # NOCHE existe en BOBINAS (19–07) y en CONVERSION (22–06): son horarios distintos por sector
        self.assertEqual(len(bundle.schedules), 5)


class CodeAndReferenceTests(unittest.TestCase):
    def rename_sector(self, old, new):
        return variant(sectors=tuple({**s, "code": new} if s["code"] == old else s for s in BUNDLE.sectors),
                       machines=tuple({**m, "sector": new} if m["sector"] == old else m for m in BUNDLE.machines),
                       schedules=tuple({**s, "sector": new} if s["sector"] == old else s for s in BUNDLE.schedules))

    def test_invalid_codes_are_rejected(self):
        for new in ("bobinas", "BOBINAS X", "B-1", "1BOBINAS", "", "B" * 33):
            with self.assertRaisesRegex(BundleError, "sector: código inválido"):
                validate(self.rename_sector("BOBINAS", new))
        for code in ("mp 1", "MP-1", "mp1", "", "M" * 33):
            with self.assertRaisesRegex(BundleError, "machine: código inválido"):
                validate(variant(machines=tuple({**m, "code": code} if m["code"] == "MP1" else m for m in BUNDLE.machines)))
        for code in ("kg", "Pack", "K G", ""):
            with self.assertRaisesRegex(BundleError, "unit: código inválido"):
                validate(variant(units=tuple({**u, "code": code} if u["code"] == "KG" else u for u in BUNDLE.units)))
        for code in ("dia", "DÍA", "D A"):
            with self.assertRaisesRegex(BundleError, "shift: código inválido"):
                validate(variant(shifts=tuple({**s, "code": code} if s["code"] == "DIA" else s for s in BUNDLE.shifts)))
        for code in ("m1 1031", "m1-1031", "M1/1031", "", "A" * 65):
            with self.assertRaisesRegex(BundleError, "article: código inválido"):
                validate(variant(articles=(({**BUNDLE.articles[0], "code": code}),) + BUNDLE.articles[1:]))

    def test_every_code_of_the_approved_bundle_already_meets_the_formats(self):
        for kind, items in (("sector", BUNDLE.sectors), ("machine", BUNDLE.machines), ("unit", BUNDLE.units), ("shift", BUNDLE.shifts), ("article", BUNDLE.articles)):
            for item in items:
                self.assertRegex(item["code"], bundle_module.CODE_PATTERNS[kind].pattern, f"{kind} {item['code']}")

    def test_duplicated_sectors_machines_and_names_are_rejected(self):
        with self.assertRaisesRegex(BundleError, "sectors: códigos duplicados"):
            validate(variant(sectors=BUNDLE.sectors + BUNDLE.sectors))
        with self.assertRaisesRegex(BundleError, "machines: códigos duplicados"):
            validate(variant(machines=BUNDLE.machines + (BUNDLE.machines[0],)))
        with self.assertRaisesRegex(BundleError, "machines: nombres repetidos"):
            validate(variant(machines=(BUNDLE.machines[0], {**BUNDLE.machines[1], "name": " mp1 "})))  # mismo nombre sin distinguir mayúsculas ni espacios
        with self.assertRaisesRegex(BundleError, "machine: nombre vacío"):
            validate(variant(machines=(BUNDLE.machines[0], {**BUNDLE.machines[1], "name": "  "})))

    def test_a_machine_without_a_valid_sector_is_rejected(self):
        for sector in ("REBOBINADO", "", None):
            with self.assertRaisesRegex(BundleError, "sector inexistente"):
                validate(variant(machines=(BUNDLE.machines[0], {**BUNDLE.machines[1], "sector": sector})))

    def test_inconsistent_article_machine_relations_are_rejected(self):
        with self.assertRaisesRegex(BundleError, "máquina inexistente"):
            validate(variant(article_machines=BUNDLE.article_machines + ({"article_code": BUNDLE.articles[0]["code"], "machine_code": "COPASA"},)))
        with self.assertRaisesRegex(BundleError, "artículo inexistente"):
            validate(variant(article_machines=BUNDLE.article_machines + ({"article_code": "NO-EXISTE", "machine_code": "MP1"},)))
        with self.assertRaisesRegex(BundleError, "relaciones duplicadas"):
            validate(variant(article_machines=BUNDLE.article_machines + (BUNDLE.article_machines[0],)))
        orphan = BUNDLE.articles[0]["code"]
        with self.assertRaisesRegex(BundleError, f"article {orphan}: producto sin relación con ninguna máquina"):
            validate(variant(article_machines=tuple(r for r in BUNDLE.article_machines if r["article_code"] != orphan)))

    def test_undefined_units_are_rejected(self):
        with self.assertRaisesRegex(BundleError, "unidad inexistente PACK"):
            validate(variant(articles=(new_article("ZZ-0003", "PACK"),) + BUNDLE.articles[1:]))
        with self.assertRaisesRegex(BundleError, "unidad inexistente"):
            validate(variant(units=tuple(u for u in BUNDLE.units if u["code"] != "KG")))


class ScheduleTests(unittest.TestCase):
    def test_a_gap_in_the_day_is_rejected_with_its_hours(self):
        with self.assertRaisesRegex(BundleError, r"BOBINAS desde 2026-01-01: minutos sin turno \(hueco\) 18:00–19:00"):
            validate(with_schedules((sch("DIA", "BOBINAS", "07:00", "18:00"), sch("NOCHE", "BOBINAS", "19:00", "07:00"))))

    def test_overlapping_shifts_are_rejected_with_their_hours(self):
        with self.assertRaisesRegex(BundleError, r"turnos solapados 18:00–19:00"):
            validate(with_schedules((sch("DIA", "BOBINAS", "07:00", "19:00"), sch("NOCHE", "BOBINAS", "18:00", "07:00"))))
        with self.assertRaisesRegex(BundleError, r"turnos solapados 00:00–23:59"):  # dos copias del mismo turno
            validate(with_schedules((sch("DIA", "BOBINAS", "00:00", "23:59"), sch("NOCHE", "BOBINAS", "23:59", "00:00"), sch("DIA2", "BOBINAS", "00:00", "23:59")), ({"code": "DIA2", "name": "Dos"},)))

    def test_midnight_crossing_shifts_are_valid_when_they_tile_the_day(self):
        validate(with_future_sector(machines=(("GAMBINI", "Gambini"),), shifts=THREE_SHIFT_CODES, schedules=THREE_SHIFTS))  # 22:00–06:00 cruza la medianoche
        with self.assertRaisesRegex(BundleError, r"turnos solapados 06:00–07:00"):  # la noche llega a las 07:00 pero la mañana empieza a las 06:00
            validate(with_future_sector(machines=(("GAMBINI", "Gambini"),), shifts=THREE_SHIFT_CODES,
                                        schedules=(THREE_SHIFTS[0], THREE_SHIFTS[1], sch("NOCHE", "CONVERSION", "22:00", "07:00"))))
        with self.assertRaisesRegex(BundleError, r"minutos sin turno \(hueco\) 05:00–06:00"):
            validate(with_future_sector(machines=(("GAMBINI", "Gambini"),), shifts=THREE_SHIFT_CODES,
                                        schedules=(THREE_SHIFTS[0], THREE_SHIFTS[1], sch("NOCHE", "CONVERSION", "22:00", "05:00"))))

    def test_the_operating_date_of_a_night_shift_is_the_day_it_starts(self):
        rows = [ScheduleRow((s["shift"],), s["shift"], s["shift"], s["shift"], datetime.strptime(s["starts_at"], "%H:%M").time(), datetime.strptime(s["ends_at"], "%H:%M").time(),
                            s["timezone"], date.fromisoformat(s["valid_from"]), None) for s in THREE_SHIFTS]
        zone = ZoneInfo(TZ)
        for (h, m), (shift, day) in {(22, 0): ("NOCHE", 13), (23, 59): ("NOCHE", 13), (0, 0): ("NOCHE", 13), (5, 59): ("NOCHE", 13), (6, 0): ("MANANA", 14), (14, 0): ("TARDE", 14)}.items():
            moment = datetime(2026, 10, 14 if h < 6 else 13 if h >= 22 else 14, h, m, tzinfo=zone)
            resolved = resolve_shift_from_schedules(rows, moment)
            self.assertEqual((resolved.shift_code, resolved.operating_date.day), (shift, day), f"{h:02d}:{m:02d}")

    def test_vigencias_must_be_well_formed_and_continuous(self):
        with self.assertRaisesRegex(BundleError, "valid_to anterior a valid_from"):
            validate(with_schedules((sch("DIA", "BOBINAS", "07:00", "19:00", "2026-01-01", "2025-12-31"), BOBINAS_SCHEDULES[1])))
        with self.assertRaisesRegex(BundleError, "hora o fecha inválida"):
            validate(with_schedules((sch("DIA", "BOBINAS", "07:00", "19:00", "2026-13-01"), BOBINAS_SCHEDULES[1])))
        with self.assertRaisesRegex(BundleError, "no hay turnos vigentes entre 2026-11-01 y 2026-11-04"):
            validate(with_schedules((sch("DIA", "BOBINAS", "07:00", "19:00", "2026-01-01", "2026-10-31"), sch("NOCHE", "BOBINAS", "19:00", "07:00", "2026-01-01", "2026-10-31"),
                                     sch("DIA", "BOBINAS", "07:00", "19:00", "2026-11-05"), sch("NOCHE", "BOBINAS", "19:00", "07:00", "2026-11-05"))))
        with self.assertRaisesRegex(BundleError, "shift_schedule duplicado"):
            validate(with_schedules(BOBINAS_SCHEDULES + (BOBINAS_SCHEDULES[0],)))

    def test_a_sector_must_use_one_valid_timezone(self):
        with self.assertRaisesRegex(BundleError, "misma zona horaria"):
            validate(with_schedules((BOBINAS_SCHEDULES[0], {**BOBINAS_SCHEDULES[1], "timezone": "America/Lima"})))
        with self.assertRaisesRegex(BundleError, "zona horaria inválida"):
            validate(with_schedules(tuple({**s, "timezone": "Mars/Olympus"} for s in BOBINAS_SCHEDULES)))

    def test_changing_hours_can_overlap_in_real_time_even_if_both_regimes_are_correct(self):
        # El caso real del inventario M1-B1: BOBINAS 07–19 → 06–18. La noche que empezó el último día del régimen viejo termina a las 07:00 y el
        # régimen nuevo ya empieza a las 06:00: esa hora daría SHIFT_AMBIGUOUS en producción. El validador lo detecta antes de importar.
        change = (sch("DIA", "BOBINAS", "07:00", "19:00", "2026-01-01", "2026-10-31"), sch("NOCHE", "BOBINAS", "19:00", "07:00", "2026-01-01", "2026-10-31"),
                  sch("DIA", "BOBINAS", "06:00", "18:00", "2026-11-01"), sch("NOCHE", "BOBINAS", "18:00", "06:00", "2026-11-01"))
        with self.assertRaisesRegex(BundleError, r"el cambio de vigencia del 2026-11-01 deja el tiempo real sin turno o con turnos solapados \(2026-11-01 06:00–2026-11-01 07:00"):
            validate(with_schedules(change))

    def test_a_clean_change_of_hours_is_accepted_and_keeps_the_old_regime(self):
        same = (sch("DIA", "BOBINAS", "07:00", "19:00", "2026-01-01", "2026-10-31"), sch("NOCHE", "BOBINAS", "19:00", "07:00", "2026-01-01", "2026-10-31"),
                sch("DIA", "BOBINAS", "07:00", "19:00", "2026-11-01"), sch("NOCHE", "BOBINAS", "19:00", "07:00", "2026-11-01"))
        validate(with_schedules(same))  # nueva vigencia con las mismas horas
        three = (sch("DIA", "BOBINAS", "07:00", "19:00", "2026-01-01", "2026-10-31"), sch("NOCHE", "BOBINAS", "19:00", "07:00", "2026-01-01", "2026-10-31"),
                 sch("MANANA", "BOBINAS", "07:00", "15:00", "2026-11-01"), sch("TARDE", "BOBINAS", "15:00", "23:00", "2026-11-01"), sch("NOCHE", "BOBINAS", "23:00", "07:00", "2026-11-01"))
        validate(with_schedules(three, THREE_SHIFT_CODES))  # el corte coincide con las 07:00: sin solape ni hueco

    def test_a_change_that_leaves_real_time_without_a_shift_is_rejected(self):
        # Régimen viejo 07–19 / 19–07 hasta el 31/10; régimen nuevo 08–20 / 20–08 desde el 1/11. Cada uno cubre el día completo por sí solo, pero el 1/11 la
        # noche vieja termina a las 07:00 y el día nuevo empieza a las 08:00 (la noche nueva solo rige para fechas operativas desde el 1/11): 07:00–08:00 sin turno.
        old = (sch("DIA", "BOBINAS", "07:00", "19:00", "2026-01-01", "2026-10-31"), sch("NOCHE", "BOBINAS", "19:00", "07:00", "2026-01-01", "2026-10-31"))
        later = old + (sch("DIA", "BOBINAS", "08:00", "20:00", "2026-11-01"), sch("NOCHE", "BOBINAS", "20:00", "08:00", "2026-11-01"))
        with self.assertRaisesRegex(BundleError, r"el cambio de vigencia del 2026-11-01 deja el tiempo real sin turno o con turnos solapados \(2026-11-01 07:00–2026-11-01 08:00"):
            validate(with_schedules(later))


if __name__ == "__main__":
    unittest.main()
