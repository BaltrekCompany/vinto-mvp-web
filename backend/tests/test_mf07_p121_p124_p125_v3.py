"""MF-07: VINTO-P1-21 pasa a la versión 2 (tabla de 27 posiciones, MD_Ejec 21) y VINTO-P1-24 / VINTO-P1-25 a la versión 3 (posiciones Comando / Medio / Transversal y promedios, MD_Ejec 26 y 25).

Correspondencia corregida (sin tocar el Excel fuente): MD_Ejec 25 describe los campos de P1-25 y MD_Ejec 26 los de P1-24; el Excel las había asignado al revés.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle:
  - P1-21 v2: 81 campos decimales opcionales (gramaje_NN / peso_seco_NN / humedad_NN, posiciones 1 a 27), «observaciones» y 4 CALCULADOS por el backend (3 promedios + posiciones utilizadas). Al menos una fila completa; ninguna a medias;
    un 0 es un valor; los promedios usan solo las filas completas.
  - P1-24 v3 / P1-25 v3: mismas claves y tipos que la v2 (solo cambian etiquetas) + promedios calculados por el backend (media aritmética simple, dos decimales, mitad hacia arriba).
  - El cliente no puede enviar calculados; las capturas de versiones anteriores no se recalculan ni se alteran; la importación es aditiva e idempotente."""

import contextlib
import dataclasses
import io
import unittest
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from app import capture_service as _capture_service
from app.ephemeral_db import build_reference_template, connect, create_database, drop_database
from app.quality import capture_service as _quality_service
from app.seed import reference
from app.seed.bundle import BundleError, _validate_fields, compute_definition_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

try:
    import test_devq2_p118_p121 as q2
    import test_f3_bobbins_api as f3
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_devq2_p118_p121 as q2
    import tests.test_f3_bobbins_api as f3
    from tests.test_assignments_api import call

P121, P124, P125 = "VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25"
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
STATE = {}
COLUMNS = ("gramaje", "peso_seco", "humedad")
K = lambda column, n: f"{column}_{n:02d}"  # noqa: E731

P121_V1 = [  # versión 1 (una captura = una posición), tal como estaba en producción
    {"key": "numero_de_bobina", "label": "Número de bobina", "value_type": "text", "required": True},
    {"key": "posicion_de_perfil", "label": "Posición de perfil", "value_type": "text", "required": True},
    {"key": "gramaje", "label": "Gramaje", "value_type": "decimal", "required": True},
    {"key": "peso_seco", "label": "Peso seco", "value_type": "decimal", "required": True},
    {"key": "observaciones", "label": "Observaciones", "value_type": "textarea", "required": False},
]
RENAMES = {  # clave técnica (sin cambios) -> etiqueta que debe tener la versión 3
    P124: {"resistencia_longitudinal_humeda_centro": "Resistencia longitudinal húmeda – Comando", "resistencia_longitudinal_humeda_medio": "Resistencia longitudinal húmeda – Medio",
           "resistencia_longitudinal_humeda_extremo": "Resistencia longitudinal húmeda – Transversal", "resistencia_transversal_humeda_centro": "Resistencia transversal húmeda – Comando",
           "resistencia_transversal_humeda_medio": "Resistencia transversal húmeda – Medio", "resistencia_transversal_humeda_extremo": "Resistencia transversal húmeda – Transversal"},
    P125: {"resistencia_longitudinal_centro_kgf": "Resistencia longitudinal – Comando kgf", "resistencia_longitudinal_medio_kgf": "Resistencia longitudinal – Medio kgf",
           "resistencia_longitudinal_extremo_kgf": "Resistencia longitudinal – Transversal kgf", "resistencia_longitudinal_humeda_centro_kgf": "Resistencia longitudinal húmeda – Comando kgf",
           "resistencia_longitudinal_humeda_medio_kgf": "Resistencia longitudinal húmeda – Medio kgf", "resistencia_longitudinal_humeda_extremo_kgf": "Resistencia longitudinal húmeda – Transversal kgf"},
}
MEANS = {
    P124: {"promedio_longitudinal_humedo": ("resistencia_longitudinal_humeda_centro", "resistencia_longitudinal_humeda_medio", "resistencia_longitudinal_humeda_extremo"),
           "promedio_transversal_humedo": ("resistencia_transversal_humeda_centro", "resistencia_transversal_humeda_medio", "resistencia_transversal_humeda_extremo")},
    P125: {"promedio_resistencia_longitudinal_kgf": ("resistencia_longitudinal_centro_kgf", "resistencia_longitudinal_medio_kgf", "resistencia_longitudinal_extremo_kgf"),
           "promedio_resistencia_longitudinal_humeda_kgf": ("resistencia_longitudinal_humeda_centro_kgf", "resistencia_longitudinal_humeda_medio_kgf", "resistencia_longitudinal_humeda_extremo_kgf")},
}


def manual(code):
    return [f for f in FORMS[code]["fields"] if f["source"] == "manual"]


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf07_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])
        f3.STATE.pop("template", None)


def fill(fields, skip=()):
    """Valores FICTICIOS (nada aquí es un límite ni una regla) para los campos manuales de una definición."""
    out = {}
    for n, f in enumerate(fields):
        if f["key"] == "observaciones" or f["key"] in skip:
            continue
        out[f["key"]] = f"{n + 1}.25" if f["value_type"] == "decimal" else (str(n) if f["value_type"] == "integer" else "dato ficticio MF-07")
    return out


def rows(entries):
    """{posición: (gramaje, peso seco, humedad)} -> valores de la tabla de P1-21."""
    return {K(column, n): value for n, triple in entries.items() for column, value in zip(COLUMNS, triple) if value is not None}


class Base(q2.BobbinBase):
    install = staticmethod(lambda connection: None)  # se usan los formularios REALES del bundle (ya publicados por la plantilla de referencia)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.current = {code: cls.version(code, FORMS[code]["version_number"]) for code in (P121, P124, P125)}
        cls.old = {}  # (código, versión) -> id de la versión histórica instalada
        cls.install_old(P121, 1, P121_V1)
        v2 = [f for f in manual(P124)]
        cls.install_old(P124, 2, v2)
        cls.install_old(P125, 2, manual(P125))

    @classmethod
    def version(cls, code, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()[0]

    @classmethod
    def install_old(cls, code, number, fields):
        """Versión HISTÓRICA publicada (como en producción antes de MF-07); el backend sigue eligiendo la más alta (la del bundle)."""
        c = cls.connection
        form_id, workflow, area, name = c.execute("SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (cls.current[code],)).fetchone()
        old = c.execute("INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id",
                        (form_id, number, name, area, workflow, "a" * 64)).fetchone()[0]
        for order, f in enumerate(fields, start=1):
            c.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s,%s,%s,%s,'manual',%s,%s)",
                      (old, f["key"], f["label"], f["value_type"], f["required"], order))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (old, cls.current[code]))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (old,))
        cls.old[(code, number)] = old

    async def asyncSetUp(self):
        await super().asyncSetUp()
        real = frozenset({P121, P124, P125})  # BobbinBase deja la política solo con la fixture sintética: se habilitan los códigos REALES (como en QA)
        for name in ("BOBBIN_CANDIDATE_FORM_CODES", "ENABLED_BOBBIN_CANDIDATE_FORM_CODES"):
            patcher = patch.object(_quality_service, name, getattr(_quality_service, name) | real)
            patcher.start()
            self.addCleanup(patcher.stop)

    def body_of(self, code, values, capture_id=None):
        return {"capture_id": capture_id or str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": values}

    async def submit_old(self, bobbin, code, number, values):
        """Captura HISTÓRICA: solo en esta llamada se fuerza la versión anterior, como ocurría antes de publicar la nueva."""
        with patch.object(_capture_service, "published_form_version", return_value=self.old[(code, number)]):
            return await self.submit(bobbin["id"], self.body_of(code, values))

    def stored(self, capture_id):
        return {k: (t, v) for k, t, v in self.connection.execute(
            """SELECT f.key, d.value_type, coalesce(d.value_decimal::text, d.value_integer::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s""", (capture_id,)).fetchall()}

    def count(self, bobbin):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (bobbin["id"],))


class DefinitionTests(Base):
    async def test_versions_and_scope_of_the_bundle(self):
        self.assertEqual({c: FORMS[c]["version_number"] for c in (P121, P124, P125)}, {P121: 2, P124: 3, P125: 3})
        self.assertEqual(sorted((f["code"], f["version_number"]) for f in BUNDLE.forms if f["version_number"] != 1), [("VINTO-P1-01", 3), ("VINTO-P1-06", 2), ("VINTO-P1-07", 2), ("VINTO-P1-10", 2), ("VINTO-P1-12", 2), ("VINTO-P1-18", 2), ("VINTO-P1-21", 2), ("VINTO-P1-22", 2), ("VINTO-P1-24", 3), ("VINTO-P1-25", 3), ("VINTO-P1-26", 2), ("VINTO-P1-29", 2), ("VINTO-P1-30", 2)],
                         "ningún otro formulario cambia (MF-08 añade P1-18, P1-22 y P1-26 v2; MF-09 añade P1-01 v3 y P1-06 v2)")
        for code in (P121, P124, P125):
            self.assertEqual(FORMS[code]["machines"], ["MP1", "MP3"])
            self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.current[code],)), "published")

    async def test_p1_21_v2_is_a_27_position_table_with_four_calculated_fields(self):
        fields = FORMS[P121]["fields"]
        keys = [f["key"] for f in fields]
        self.assertEqual(len(fields), 86)
        self.assertEqual(keys[:6], ["gramaje_01", "peso_seco_01", "humedad_01", "gramaje_02", "peso_seco_02", "humedad_02"])
        self.assertEqual([K(c, n) for n in range(1, 28) for c in COLUMNS], keys[:81])
        self.assertEqual(keys[81:], ["observaciones", "promedio_gramaje", "promedio_peso_seco", "promedio_humedad", "posiciones_utilizadas"])
        for f in fields[:81]:
            self.assertEqual((f["value_type"], f["source"], f["required"]), ("decimal", "manual", False), f["key"])
        calc = {f["key"]: f for f in fields if f["source"] == "calculated"}
        self.assertEqual({k: (v["value_type"], v["required"]) for k, v in calc.items()}, {"promedio_gramaje": ("decimal", False), "promedio_peso_seco": ("decimal", False), "promedio_humedad": ("decimal", False), "posiciones_utilizadas": ("integer", False)})
        for removed in ("numero_de_bobina", "posicion_de_perfil", "gramaje", "peso_seco"):
            self.assertNotIn(removed, keys)
        self.assertEqual([f["display_order"] for f in fields], list(range(1, 87)))

    async def test_p1_24_and_p1_25_v3_only_rename_labels_and_add_the_approved_averages(self):
        for code in (P124, P125):
            new = {f["key"]: f for f in FORMS[code]["fields"]}
            old = {f["key"]: f for f in manual(code)}
            self.assertEqual(sorted(k for k, f in new.items() if f["source"] == "calculated"), sorted(MEANS[code]))
            self.assertEqual(sorted(k for k in new if new[k]["source"] == "manual"), sorted(old), "no se añaden ni se quitan campos digitables")
            for key, label in RENAMES[code].items():
                self.assertEqual(new[key]["label"], label, key)
                self.assertEqual((new[key]["value_type"], new[key]["required"], new[key]["source"]), ("decimal", True, "manual"))
            for key, f in new.items():
                if key not in RENAMES[code] and f["source"] == "manual":
                    self.assertEqual(f["label"], old[key]["label"])  # el resto no cambia de etiqueta
            for key in MEANS[code]:
                self.assertEqual((new[key]["value_type"], new[key]["required"]), ("decimal", False))
        # P1-25: Comando / Medio / Transversal en el orden de siempre; las dos elongaciones existen UNA vez; MF-06 intacto
        keys = [f["key"] for f in FORMS[P125]["fields"]]
        self.assertEqual(keys[0], "caudal_rh_ml_min")
        self.assertEqual(keys[-2:], ["n_cortes", "observaciones"])
        self.assertEqual(keys.count("elongacion_media_longitudinal"), 1)
        self.assertEqual(keys.count("elongacion_media_transversal"), 1)
        self.assertLess(keys.index("resistencia_longitudinal_extremo_kgf"), keys.index("promedio_resistencia_longitudinal_kgf"))
        self.assertLess(keys.index("promedio_resistencia_longitudinal_kgf"), keys.index("elongacion_media_longitudinal"))
        self.assertLess(keys.index("resistencia_longitudinal_humeda_extremo_kgf"), keys.index("promedio_resistencia_longitudinal_humeda_kgf"))
        for removed in ("numero_de_bobina", "producto", "gramaje_laboratorio_g_m2"):
            self.assertNotIn(removed, keys)
        for removed in ("numero_de_bobina", "producto"):
            self.assertNotIn(removed, [f["key"] for f in FORMS[P124]["fields"]])
        self.assertEqual((len(FORMS[P124]["fields"]), len(FORMS[P125]["fields"])), (12, 15))

    async def test_labels_distinguish_direction_from_position(self):
        """La dirección (longitudinal / transversal) y la posición (Comando / Medio / Transversal) se separan con « – »; «Transversal» como posición nunca se sustituye por otra denominación."""
        labels = [f["label"] for code in (P124, P125) for f in FORMS[code]["fields"]]
        self.assertFalse([label for label in labels if "Transmisión" in label or "extremo" in label.lower() or " centro" in label.lower()])
        self.assertIn("Resistencia transversal húmeda – Transversal", labels)
        self.assertIn("Resistencia longitudinal húmeda – Transversal kgf", labels)


class P121Tests(Base):
    async def test_a_single_complete_row_is_saved_with_averages_equal_to_its_values(self):
        assignment, bobbin = await self.bobbin("MP1")
        reply = await self.submit(bobbin["id"], self.body_of(P121, rows({1: ("90.5", "1.25", "5.5")})))
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["bobbin"], capture["machine"]["code"]), (2, {"id": bobbin["id"], "code": bobbin["code"]}, "MP1"))
        self.assertEqual(capture["values"], {"gramaje_01": "90.5", "peso_seco_01": "1.25", "humedad_01": "5.5", "promedio_gramaje": "90.50", "promedio_peso_seco": "1.25", "promedio_humedad": "5.50", "posiciones_utilizadas": 1})
        stored = self.stored(capture["id"])
        self.assertEqual(len(stored), 7, "solo se guardan las celdas digitadas y los calculados: nada de ceros en las posiciones vacías")
        self.assertEqual(stored["posiciones_utilizadas"], ("integer", "1"))
        self.assertEqual(stored["promedio_gramaje"], ("decimal", "90.50"))
        self.assertEqual(self.scalar("SELECT bobbin_id::text FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), bobbin["id"])

    async def test_several_complete_rows_use_only_complete_rows_and_round_half_up(self):
        _, bobbin = await self.bobbin("MP3")
        values = rows({1: ("10.00", "1.000", "4"), 2: ("10.01", "2.000", "5"), 5: ("20", "0.5", "6.5"), 27: ("0", "0", "0")})
        reply = await self.submit(bobbin["id"], self.body_of(P121, {**values, "observaciones": "  nota  "}))
        self.assertEqual(reply.status, 201, reply.text)
        got = reply.json()["capture"]["values"]
        self.assertEqual(got["posiciones_utilizadas"], 4)
        self.assertEqual(got["promedio_gramaje"], "10.00")  # (10 + 10.01 + 20 + 0) / 4 = 10.0025
        self.assertEqual(got["promedio_peso_seco"], "0.88")  # (1 + 2 + 0.5 + 0) / 4 = 0.875 -> mitad hacia arriba
        self.assertEqual(got["promedio_humedad"], "3.88")  # (4 + 5 + 6.5 + 0) / 4 = 3.875
        self.assertEqual(got["observaciones"], "nota")
        for n in (3, 4, 6, 26):
            self.assertNotIn(K("gramaje", n), got, "las filas vacías no se rellenan")

    async def test_zero_is_a_value_and_not_an_empty_cell(self):
        _, bobbin = await self.bobbin("MP1")
        ok = await self.submit(bobbin["id"], self.body_of(P121, rows({3: ("0", "0", "0")})))
        self.assertEqual(ok.status, 201, ok.text)
        got = ok.json()["capture"]["values"]
        self.assertEqual((got["gramaje_03"], got["promedio_gramaje"], got["promedio_humedad"], got["posiciones_utilizadas"]), ("0", "0.00", "0.00", 1))
        # un «0» solo en una fila no la completa: es una fila a medias
        partial = await self.submit(bobbin["id"], self.body_of(P121, {**rows({1: ("1", "2", "3")}), "humedad_02": "0"}))
        self.assertEqual(partial.status, 422, partial.text)
        self.assertIn("posición 2", partial.text)

    async def test_partial_rows_and_captures_without_complete_rows_are_rejected_and_leave_nothing(self):
        _, bobbin = await self.bobbin("MP1")
        full = rows({1: ("1", "2", "3")})
        bad = [({**full, "gramaje_04": "7"}, "posición 4"), ({**full, "peso_seco_09": "7", "humedad_09": "8"}, "posición 9"), ({**full, "humedad_27": "1"}, "posición 27"),
               ({}, "al menos una posición completa"), ({"observaciones": "solo texto"}, "al menos una posición completa"), ({"gramaje_01": "", "peso_seco_01": "  ", "humedad_01": None}, "al menos una posición completa"),
               ({"gramaje_01": "1", "peso_seco_01": "2"}, "posición 1")]
        for values, needle in bad:
            reply = await self.submit(bobbin["id"], self.body_of(P121, values))
            self.assertEqual(reply.status, 422, (values, reply.text))
            self.assertIn(needle, reply.text)
        self.assertEqual(self.count(bobbin), 0, "ningún intento inválido dejó filas")

    async def test_invalid_numbers_unknown_positions_removed_fields_and_client_sent_calculated_values_are_rejected(self):
        _, bobbin = await self.bobbin("MP1")
        full = rows({1: ("1", "2", "3")})
        for extra in ({"gramaje_01": "abc"}, {"gramaje_28": "1"}, {"gramaje_00": "1"}, {"numero_de_bobina": bobbin["code"]}, {"posicion_de_perfil": "3"}, {"gramaje": "1"}, {"peso_seco": "1"},
                      {"promedio_gramaje": "1.00"}, {"promedio_peso_seco": "1"}, {"promedio_humedad": "1"}, {"posiciones_utilizadas": 1}):
            reply = await self.submit(bobbin["id"], self.body_of(P121, {**full, **extra}))
            self.assertEqual(reply.status, 422, (extra, reply.text))
        self.assertIn("calculado", (await self.submit(bobbin["id"], self.body_of(P121, {**full, "promedio_gramaje": "9"}))).text)
        self.assertEqual(self.count(bobbin), 0)

    async def test_retry_is_idempotent_with_the_stored_calculated_values(self):
        _, bobbin = await self.bobbin("MP1")
        body = self.body_of(P121, rows({1: ("1.1", "2.2", "3.3"), 2: ("2.2", "3.3", "4.4")}))
        first = await self.submit(bobbin["id"], body)
        again = await self.submit(bobbin["id"], body)
        self.assertEqual((first.status, again.status), (201, 200), (first.text, again.text))
        self.assertEqual(first.json()["capture"], again.json()["capture"])
        self.assertEqual(self.count(bobbin), 1)
        changed = await self.submit(bobbin["id"], {**body, "values": rows({1: ("1.1", "2.2", "3.3")})})
        self.assertEqual(changed.status, 409, changed.text)

    async def test_the_bobbin_comes_from_the_route_and_quality_release_is_untouched(self):
        _, a = await self.bobbin("MP1")
        _, b = await self.bobbin("MP1")
        before = self.release(a["id"]), self.release(b["id"])
        reply = await self.submit(a["id"], self.body_of(P121, rows({1: ("1", "2", "3")})))
        self.assertEqual(reply.json()["capture"]["bobbin"]["code"], a["code"])
        self.assertEqual((self.release(a["id"]), self.release(b["id"])), before)
        self.assertEqual(self.count(b), 0)

    async def test_version_1_captures_stay_readable_next_to_version_2(self):
        _, bobbin = await self.bobbin("MP1")
        old = await self.submit_old(bobbin, P121, 1, {"numero_de_bobina": bobbin["code"], "posicion_de_perfil": "P7", "gramaje": "81.5", "peso_seco": "1.5", "observaciones": "histórica"})
        self.assertEqual(old.status, 201, old.text)
        old_capture = old.json()["capture"]
        self.assertEqual(old_capture["form"]["version_number"], 1)
        self.assertEqual(set(old_capture["values"]), {"numero_de_bobina", "posicion_de_perfil", "gramaje", "peso_seco", "observaciones"}, "sin promedios inventados")
        new = await self.submit(bobbin["id"], self.body_of(P121, rows({1: ("1", "2", "3")})))
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 2)
        for item in (old_capture, new.json()["capture"]):
            got = await self.read(f"/api/quality/captures/{item['id']}")
            self.assertEqual((got.status, got.json()["values"]), (200, item["values"]))
        listed = await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={P121}")
        self.assertEqual({c["form"]["version_number"] for c in listed.json()}, {1, 2})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[(P121, 1)],)), 5)


class P124P125Tests(Base):
    def values(self, code):
        return fill(manual(code))

    async def test_averages_are_the_exact_arithmetic_mean_of_the_three_positions_with_two_decimals(self):
        _, bobbin = await self.bobbin("MP1")
        cases = {P124: {"resistencia_longitudinal_humeda_centro": "1.00", "resistencia_longitudinal_humeda_medio": "2.00", "resistencia_longitudinal_humeda_extremo": "2.00",
                        "resistencia_transversal_humeda_centro": "0.10", "resistencia_transversal_humeda_medio": "0.20", "resistencia_transversal_humeda_extremo": "0.35"},
                 P125: {"resistencia_longitudinal_centro_kgf": "10", "resistencia_longitudinal_medio_kgf": "11", "resistencia_longitudinal_extremo_kgf": "11.5",
                        "resistencia_longitudinal_humeda_centro_kgf": "0", "resistencia_longitudinal_humeda_medio_kgf": "0", "resistencia_longitudinal_humeda_extremo_kgf": "0.01"}}
        expected = {P124: {"promedio_longitudinal_humedo": "1.67", "promedio_transversal_humedo": "0.22"},  # 5/3 = 1.666… ; 0.65/3 = 0.2166…
                    P125: {"promedio_resistencia_longitudinal_kgf": "10.83", "promedio_resistencia_longitudinal_humeda_kgf": "0.00"}}  # 32.5/3 = 10.8333 ; 0.01/3 = 0.00333
        for code in (P124, P125):
            reply = await self.submit(bobbin["id"], self.body_of(code, {**self.values(code), **cases[code]}))
            self.assertEqual(reply.status, 201, (code, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual(capture["form"]["version_number"], 3)
            for key, value in expected[code].items():
                self.assertEqual(capture["values"][key], value, (code, key))
                self.assertEqual(self.stored(capture["id"])[key], ("decimal", value))
        # empate exacto: mitad hacia arriba (0.005 -> 0.01); el negativo se aleja de cero
        tie = await self.submit(bobbin["id"], self.body_of(P124, {**self.values(P124), "resistencia_longitudinal_humeda_centro": "0.01", "resistencia_longitudinal_humeda_medio": "0.01", "resistencia_longitudinal_humeda_extremo": "0.01"}))
        self.assertEqual(tie.json()["capture"]["values"]["promedio_longitudinal_humedo"], "0.01")
        half = await self.submit(bobbin["id"], self.body_of(P124, {**self.values(P124), "resistencia_transversal_humeda_centro": "0.01", "resistencia_transversal_humeda_medio": "0.00", "resistencia_transversal_humeda_extremo": "0.00"}))
        self.assertEqual(half.json()["capture"]["values"]["promedio_transversal_humedo"], "0.00")  # 0.01/3 = 0.0033
        self.assertEqual(_quality_service.mean_two_decimals([Decimal("0.005")]), Decimal("0.01"))
        self.assertEqual(_quality_service.mean_two_decimals([Decimal("-0.005")]), Decimal("-0.01"))
        self.assertEqual(str(_quality_service.mean_two_decimals([Decimal("-0.001")])), "0.00")

    async def test_each_average_uses_exactly_its_own_three_measurements(self):
        _, bobbin = await self.bobbin("MP3")
        self.assertEqual({c: {k: tuple(v) for k, v in m.items()} for c, m in _quality_service.MEAN_RULES.items()}, MEANS)
        for code in (P124, P125):
            for key, sources in MEANS[code].items():
                self.assertEqual(len(sources), 3)
                self.assertTrue(all(s in {f["key"] for f in manual(code)} for s in sources))
        values = {**self.values(P125), "elongacion_media_longitudinal": "99", "elongacion_media_transversal": "98"}
        reply = await self.submit(bobbin["id"], self.body_of(P125, values))
        got = reply.json()["capture"]["values"]
        dry = [Decimal(values[k]) for k in MEANS[P125]["promedio_resistencia_longitudinal_kgf"]]
        self.assertEqual(Decimal(got["promedio_resistencia_longitudinal_kgf"]), (sum(dry) / 3).quantize(Decimal("0.01")), "las elongaciones no entran en el promedio")

    async def test_clients_cannot_send_averages_and_mf06_rules_still_apply(self):
        _, bobbin = await self.bobbin("MP1")
        for code in (P124, P125):
            for key in MEANS[code]:
                reply = await self.submit(bobbin["id"], self.body_of(code, {**self.values(code), key: "1.00"}))
                self.assertEqual(reply.status, 422, (code, key, reply.text))
                self.assertIn("calculado", reply.text)
            for key in ("numero_de_bobina", "producto"):
                self.assertEqual((await self.submit(bobbin["id"], self.body_of(code, {**self.values(code), key: "x"}))).status, 422)
            missing = {k: v for k, v in self.values(code).items() if k != "crepado"}
            self.assertEqual((await self.submit(bobbin["id"], self.body_of(code, missing))).status, 422)
        base = {k: v for k, v in self.values(P125).items() if k not in ("n_cortes", "caudal_rh_ml_min")}
        for bad in (-1, "1.5", "abc", "", None):  # # Cortes: entero no negativo obligatorio (MF-06)
            self.assertEqual((await self.submit(bobbin["id"], self.body_of(P125, {**base, "n_cortes": bad}))).status, 422, bad)
        self.assertEqual((await self.submit(bobbin["id"], self.body_of(P125, base))).status, 422)
        ok = await self.submit(bobbin["id"], self.body_of(P125, {**base, "n_cortes": 0}))  # Caudal RH opcional
        self.assertEqual(ok.status, 201, ok.text)
        self.assertEqual(ok.json()["capture"]["values"]["n_cortes"], 0)
        self.assertNotIn("caudal_rh_ml_min", ok.json()["capture"]["values"])
        self.assertEqual(self.count(bobbin), 1)

    async def test_previous_versions_stay_readable_and_are_never_recalculated(self):
        for code, previous in ((P124, 2), (P125, 2)):
            _, bobbin = await self.bobbin("MP1")
            old = await self.submit_old(bobbin, code, previous, self.values(code))
            self.assertEqual(old.status, 201, (code, old.text))
            old_capture = old.json()["capture"]
            self.assertEqual(old_capture["form"]["version_number"], 2)
            for key in MEANS[code]:
                self.assertNotIn(key, old_capture["values"], "no se inventan promedios para registros históricos")
            new = await self.submit(bobbin["id"], self.body_of(code, self.values(code)))
            self.assertEqual(new.json()["capture"]["form"]["version_number"], 3)
            for item in (old_capture, new.json()["capture"]):
                got = await self.read(f"/api/quality/captures/{item['id']}")
                self.assertEqual((got.status, got.json()["values"]), (200, item["values"]))
            self.assertEqual({c["form"]["version_number"] for c in (await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")).json()}, {2, 3})
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (old_capture["id"],)), len(self.values(code)), "la captura histórica queda tal cual")

    async def test_retry_is_idempotent_for_version_3(self):
        _, bobbin = await self.bobbin("MP1")
        for code in (P124, P125):
            body = self.body_of(code, self.values(code))
            first, again = await self.submit(bobbin["id"], body), await self.submit(bobbin["id"], body)
            self.assertEqual((first.status, again.status), (201, 200), code)
            self.assertEqual(first.json()["capture"], again.json()["capture"])

    async def test_quality_release_is_untouched(self):
        _, bobbin = await self.bobbin("MP1")
        before = self.release(bobbin["id"])
        for code in (P124, P125):
            self.assertEqual((await self.submit(bobbin["id"], self.body_of(code, self.values(code)))).status, 201)
        self.assertEqual(self.release(bobbin["id"]), before)


class BundleValidationTests(unittest.TestCase):
    def check(self, **changes):
        field = {"key": "promedio_x", "label": "Promedio X", "value_type": "decimal", "source": "calculated", "required": False, "unit": None, "display_order": 1, **changes}
        _validate_fields([field], {}, "VINTO-TEST")

    def test_calculated_fields_are_importable_only_when_not_required(self):
        self.check()
        with self.assertRaises(BundleError):
            self.check(required=True)

    def test_automatic_and_unknown_sources_are_still_rejected(self):
        for source in ("automatic", "otro"):
            with self.assertRaises(BundleError):
                self.check(source=source)
        self.check(source="manual")


def variant(checksum, spec):
    """El bundle vigente con algunas versiones de formulario sustituidas: {código: (versión, campos)}. Reproduce el estado de producción antes de MF-07."""
    forms = []
    for form in BUNDLE.forms:
        if form["code"] in spec:
            number, fields = spec[form["code"]]
            fields = [{"source": "manual", "unit": None, **f, "display_order": n} for n, f in enumerate(fields, start=1)]
            form = {**form, "version_number": number, "fields": fields}
            form["definition_checksum"] = compute_definition_checksum(form)
        forms.append(form)
    return dataclasses.replace(BUNDLE, source_checksum=checksum, forms=tuple(forms))


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción ya tiene P1-21 v1, P1-24 v1/v2 y P1-25 v1/v2: el importador debe AÑADIR P1-21 v2, P1-24 v3 y P1-25 v3 y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf07_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        v1_24 = [{"key": "numero_de_bobina", "label": "Número de bobina", "value_type": "text", "required": True}, {"key": "producto", "label": "Producto", "value_type": "text", "required": True}] + manual(P124)
        v1_25 = [{"key": "numero_de_bobina", "label": "Número de bobina", "value_type": "text", "required": True}, {"key": "producto", "label": "Producto", "value_type": "text", "required": True},
                 {"key": "gramaje_laboratorio_g_m2", "label": "Gramaje laboratorio g/m²", "value_type": "decimal", "required": True}] + [f for f in manual(P125) if f["key"] not in ("caudal_rh_ml_min", "n_cortes")]
        reference.apply(cls.connection, variant("1" * 64, {P121: (1, P121_V1), P124: (1, v1_24), P125: (1, v1_25)}))
        reference.apply(cls.connection, variant("2" * 64, {P121: (1, P121_V1), P124: (2, manual(P124)), P125: (2, manual(P125))}))

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def snapshot(self, where):
        c = self.connection
        versions = c.execute(f"""SELECT f.code, v.version_number, v.status, v.definition_checksum, v.published_at FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                 WHERE {where} ORDER BY 1, 2""").fetchall()
        fields = c.execute(f"""SELECT f.code, v.version_number, d.id, d.key, d.label, d.value_type, d.source, d.required, d.display_order FROM vinto_config.field_definition d
                               JOIN vinto_config.form_version v ON v.id = d.form_version_id JOIN vinto_config.form f ON f.id = v.form_id WHERE {where} ORDER BY 1, 2, 9""").fetchall()
        return versions, fields

    def test_the_bundle_adds_only_the_three_new_versions_and_is_idempotent(self):
        old_where = f"(f.code = '{P121}' AND v.version_number = 1) OR (f.code IN ('{P124}','{P125}') AND v.version_number IN (1, 2))"
        other_where = f"f.code NOT IN ('{P121}','{P124}','{P125}')"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual((len(old[0]), len(old[1])), (5, 5 + 12 + 10 + 14 + 13))
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 3)
        self.assertEqual(dry.counts["field"]["create"], 86 + 12 + 15)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 6)
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "las versiones anteriores y sus campos quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        for code, expected in ((P121, [(1, "published"), (2, "published")]), (P124, [(1, "published"), (2, "published"), (3, "published")]), (P125, [(1, "published"), (2, "published"), (3, "published")])):
            self.assertEqual(self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (code,)).fetchall(), expected)
        sources = self.connection.execute("""SELECT f.code, d.source, count(*) FROM vinto_config.field_definition d JOIN vinto_config.form_version v ON v.id = d.form_version_id JOIN vinto_config.form f ON f.id = v.form_id
                                             WHERE (f.code, v.version_number) IN (('VINTO-P1-21',2),('VINTO-P1-24',3),('VINTO-P1-25',3)) GROUP BY 1, 2 ORDER BY 1, 2""").fetchall()
        self.assertEqual(sources, [(P121, "calculated", 4), (P121, "manual", 82), (P124, "calculated", 2), (P124, "manual", 10), (P125, "calculated", 2), (P125, "manual", 13)])
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")


if __name__ == "__main__":
    unittest.main()
