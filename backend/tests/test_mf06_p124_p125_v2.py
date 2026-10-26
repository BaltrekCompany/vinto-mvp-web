"""MF-06: VINTO-P1-24 (Propiedades físicas en húmedo) y VINTO-P1-25 (Resistencia en húmedo-curado) pasan a la versión 2.

  - P1-24 v2 (MD_Ejec 22): sin «numero_de_bobina» ni «producto» (10 campos).
  - P1-25 v2 (MD_Ejec 27, 28 y 29): sin «numero_de_bobina», «producto» ni «gramaje_laboratorio_g_m2»; con «caudal_rh_ml_min» al inicio y «n_cortes» al final (13 campos).

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle (no fixtures): la versión 1 sigue publicada e intacta, la versión 2 es la que elige el backend
para capturas nuevas, y una captura histórica de la versión 1 sigue siendo legible. La ruta de Calidad por bobina toma la bobina de la URL, por lo que ya no necesita que se digite su número."""

import contextlib
import dataclasses
import io
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import capture_service as _capture_service
from app.ephemeral_db import build_reference_template, connect, create_database, drop_database
from app.quality import capture_service as _quality_service
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle
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

P124, P125 = "VINTO-P1-24", "VINTO-P1-25"
REMOVED = {P124: ("numero_de_bobina", "producto"), P125: ("numero_de_bobina", "producto", "gramaje_laboratorio_g_m2")}
ADDED = {P124: (), P125: ("caudal_rh_ml_min", "n_cortes")}
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf06_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])
        f3.STATE.pop("template", None)


def values_for(fields, skip=()):
    """Valores FICTICIOS (nada aquí es un límite ni una regla): decimal «n.25», texto fijo; `observaciones` se omite."""
    out = {}
    for n, (key, kind) in enumerate(fields):
        if key == "observaciones" or key in skip:
            continue
        out[key] = f"{n}.25" if kind == "decimal" else "dato ficticio MF-06"
    return out


class Base(q2.BobbinBase):
    install = staticmethod(lambda connection: None)  # se usan los formularios REALES del bundle (ya publicados por la plantilla de referencia)

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.v1, cls.v2 = {}, {}
        for code in (P124, P125):
            cls.v2[code] = cls.version(code, 2)
            cls.v1[code] = cls.install_v1(code)

    @classmethod
    def version(cls, code, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()[0]

    @classmethod
    def install_v1(cls, code):
        """Reproduce el estado de producción ANTES de importar la v2: la v1 (con los campos que se retiran) publicada para las mismas máquinas. Se obtiene de la definición legacy del bundle anterior."""
        c = cls.connection
        form_id, workflow, area, name = c.execute("SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (cls.v2[code],)).fetchone()
        v1 = c.execute("""INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s, 1, %s, %s, %s, %s) RETURNING id""",
                       (form_id, name, area, workflow, "a" * 64)).fetchone()[0]
        for order, f in enumerate(legacy_fields(code), start=1):
            c.execute("""INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s,%s,%s,%s,'manual',%s,%s)""",
                      (v1, f["key"], f["label"], f["value_type"], f["required"], order))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (v1, cls.v2[code]))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (v1,))
        return v1

    async def asyncSetUp(self):
        await super().asyncSetUp()
        # BobbinBase deja la política solo con la fixture sintética: aquí se habilitan los códigos REALES (como en la configuración de QA) en ambos conjuntos, el «conocido» y el «habilitado»
        real = frozenset({P124, P125})
        for name in ("BOBBIN_CANDIDATE_FORM_CODES", "ENABLED_BOBBIN_CANDIDATE_FORM_CODES"):
            patcher = patch.object(_quality_service, name, getattr(_quality_service, name) | real)
            patcher.start()
            self.addCleanup(patcher.stop)

    def definition(self, version):
        return [tuple(r) for r in self.connection.execute("SELECT key, value_type FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY display_order", (version,)).fetchall()]

    def body_of(self, code, values):
        return {"capture_id": str(uuid4()), "form_code": code, "device_key": str(uuid4()), "values": values}

    async def submit_v1(self, bobbin, code):
        """Captura HISTÓRICA: solo en esta llamada se fuerza la elección de la v1, como ocurría antes de publicar la v2."""
        values = {**values_for(self.definition(self.v1[code])), "numero_de_bobina": bobbin["code"]}
        with patch.object(_capture_service, "published_form_version", return_value=self.v1[code]):
            return await self.submit(bobbin["id"], self.body_of(code, values))


def legacy_fields(code):
    """Campos de la versión 1 (antes de MF-06): la v2 del bundle con los campos retirados en su posición original y sin los añadidos."""
    v2 = [{**f} for f in FORMS[code]["fields"] if f["key"] not in ADDED[code]]
    head = [{"key": "numero_de_bobina", "label": "Número de bobina", "value_type": "text", "required": True}, {"key": "producto", "label": "Producto", "value_type": "text", "required": True}]
    if code == P125:  # P1-25: tras «crepado» venía «gramaje_laboratorio_g_m2» (ver bundle anterior)
        crepado = next(i for i, f in enumerate(v2) if f["key"] == "crepado")
        v2.insert(crepado + 1, {"key": "gramaje_laboratorio_g_m2", "label": "Gramaje laboratorio g/m²", "value_type": "decimal", "required": True})
    return head + v2


class DefinitionTests(Base):
    async def test_versions_and_bundle_match_the_request(self):
        for code in (P124, P125):
            v1, v2 = [k for k, _ in self.definition(self.v1[code])], [k for k, _ in self.definition(self.v2[code])]
            self.assertEqual(FORMS[code]["version_number"], 2)
            self.assertEqual(v2, [f["key"] for f in FORMS[code]["fields"]])
            self.assertEqual(sorted(set(v1) - set(v2)), sorted(REMOVED[code]), code)
            self.assertEqual(sorted(set(v2) - set(v1)), sorted(ADDED[code]), code)
            for key in REMOVED[code]:
                self.assertNotIn(key, v2)
        self.assertEqual((len(self.definition(self.v1[P124])), len(self.definition(self.v2[P124]))), (12, 10))
        self.assertEqual((len(self.definition(self.v1[P125])), len(self.definition(self.v2[P125]))), (14, 13))

    async def test_the_new_p1_25_fields_are_at_the_requested_positions_and_are_digitable(self):
        rows = self.connection.execute("SELECT key, label, value_type, source, required, display_order FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY display_order", (self.v2[P125],)).fetchall()
        self.assertEqual(rows[0][:5], ("caudal_rh_ml_min", "Caudal RH [ml/min]", "decimal", "manual", False))
        self.assertEqual(rows[-1][:5], ("n_cortes", "# Cortes", "decimal", "manual", False))
        self.assertEqual([r[5] for r in rows], list(range(1, 14)))
        # los demás campos conservan tipo y obligatoriedad de la v1
        rest = "SELECT key, value_type, required FROM vinto_config.field_definition WHERE form_version_id = %s AND key <> ALL(%s) ORDER BY key"
        self.assertEqual(self.connection.execute(rest, (self.v1[P125], list(REMOVED[P125]) + list(ADDED[P125]))).fetchall(), self.connection.execute(rest, (self.v2[P125], list(REMOVED[P125]) + list(ADDED[P125]))).fetchall())
        rest24 = self.connection.execute(rest, (self.v1[P124], list(REMOVED[P124]))).fetchall()
        self.assertEqual(rest24, self.connection.execute(rest, (self.v2[P124], list(REMOVED[P124]))).fetchall())

    async def test_only_the_three_expected_forms_are_at_version_2_in_the_bundle(self):
        self.assertEqual(sorted(f["code"] for f in BUNDLE.forms if f["version_number"] != 1), ["VINTO-P1-01", P124, P125])


class WriteTests(Base):
    async def test_history_stays_readable_and_new_captures_use_version_2_without_the_removed_fields(self):
        for code in (P124, P125):
            for machine in ("MP1", "MP3"):
                _, bobbin = await self.bobbin(machine)
                old = await self.submit_v1(bobbin, code)
                self.assertEqual(old.status, 201, (code, machine, old.text))
                old_capture = old.json()["capture"]
                self.assertEqual((old_capture["form"]["version_number"], old_capture["values"]["numero_de_bobina"]), (1, bobbin["code"]))
                values = values_for(self.definition(self.v2[code]))
                new = await self.submit(bobbin["id"], self.body_of(code, values))
                self.assertEqual(new.status, 201, (code, machine, new.text))
                capture = new.json()["capture"]
                self.assertEqual((capture["form"]["version_number"], capture["bobbin"], capture["machine"]["code"]), (2, {"id": bobbin["id"], "code": bobbin["code"]}, machine))
                self.assertEqual(capture["values"], values)
                for key in REMOVED[code]:
                    self.assertNotIn(key, capture["values"])
                    self.assertIn(key, old_capture["values"], "la captura histórica conserva sus valores")
                # ambas se pueden leer, cada una con su definición, y el historial por bobina/formulario las devuelve juntas
                for item in (old_capture, capture):
                    got = await self.read(f"/api/quality/captures/{item['id']}")
                    self.assertEqual((got.status, got.json()["values"]), (200, item["values"]))
                listed = await self.read(f"/api/quality/bobbins/{bobbin['id']}/captures?form_code={code}")
                self.assertEqual({c["form"]["version_number"] for c in listed.json()}, {1, 2})
                # PostgreSQL: los valores históricos de la v1 siguen allí
                self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (old_capture["id"],)), len(self.definition(self.v1[code])) - 1)  # observaciones omitida
                self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.v1[code],)), len(self.definition(self.v1[code])))

    async def test_the_new_p1_25_fields_are_saved_typed_and_are_optional(self):
        _, bobbin = await self.bobbin("MP1")
        base = values_for(self.definition(self.v2[P125]), skip=ADDED[P125])
        # 1) con los dos campos nuevos digitados: se guardan tipados (decimal exacto)
        full = {**base, "caudal_rh_ml_min": "12.5", "n_cortes": "3"}
        reply = await self.submit(bobbin["id"], self.body_of(P125, full))
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual((capture["values"]["caudal_rh_ml_min"], capture["values"]["n_cortes"]), ("12.5", "3"))
        stored = self.rows(capture["id"])
        self.assertEqual((stored["caudal_rh_ml_min"], stored["n_cortes"]), ("decimal:12.5", "decimal:3"))
        # 2) sin ellos: es válido (opcionales, a confirmar con el funcional) y no se guarda nada para ellos
        other = await self.submit(bobbin["id"], self.body_of(P125, base))
        self.assertEqual(other.status, 201, other.text)
        self.assertNotIn("caudal_rh_ml_min", other.json()["capture"]["values"])
        # 3) un valor no numérico en cualquiera de los dos es 422 y no deja filas
        count = self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (bobbin["id"],))
        for key in ADDED[P125]:
            bad = await self.submit(bobbin["id"], self.body_of(P125, {**base, key: "abc"}))
            self.assertEqual(bad.status, 422, (key, bad.text))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (bobbin["id"],)), count)

    async def test_removed_fields_are_not_required_and_are_rejected_if_sent(self):
        for code in (P124, P125):
            _, bobbin = await self.bobbin("MP3")
            good = values_for(self.definition(self.v2[code]))
            for key in REMOVED[code]:  # ya no existe en la v2: enviarlo es un campo desconocido (el frontend nunca lo envía)
                reply = await self.submit(bobbin["id"], self.body_of(code, {**good, key: "x"}))
                self.assertEqual(reply.status, 422, (code, key, reply.text))
            # un obligatorio vigente sigue siéndolo
            missing = {k: v for k, v in good.items() if k != "crepado"}
            self.assertEqual((await self.submit(bobbin["id"], self.body_of(code, missing))).status, 422, code)
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (bobbin["id"],)), 0, "ninguno de los intentos dejó filas")
            ok = await self.submit(bobbin["id"], self.body_of(code, good))
            self.assertEqual(ok.status, 201, (code, ok.text))

    async def test_the_bobbin_comes_from_the_route_and_quality_release_is_untouched(self):
        _, a = await self.bobbin("MP1")
        _, b = await self.bobbin("MP1")
        before = self.release(a["id"]), self.release(b["id"])
        for code in (P124, P125):
            reply = await self.submit(a["id"], self.body_of(code, values_for(self.definition(self.v2[code]))))
            capture = reply.json()["capture"]
            self.assertEqual(capture["bobbin"]["code"], a["code"], "el número de bobina sale de la bobina seleccionada, no de un campo digitado")
            self.assertEqual(self.scalar("SELECT bobbin_id::text FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), a["id"])
        self.assertEqual((self.release(a["id"]), self.release(b["id"])), before)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE bobbin_id = %s", (b["id"],)), 0)

    async def test_the_declared_bobbin_check_still_applies_to_forms_that_declare_the_field(self):
        """P1-21 y P1-28 siguen declarando «numero_de_bobina»: el contraste con la bobina seleccionada no se pierde para ellos."""
        self.assertEqual(_quality_service.BOBBIN_CODE_FIELDS["VINTO-P1-21"], "numero_de_bobina")
        self.assertEqual(_quality_service.BOBBIN_CODE_FIELDS["VINTO-P1-28"], "numero_de_bobina")
        _, bobbin = await self.bobbin("MP1")
        # P1-24 v1 histórica declara el campo: un número contradictorio se sigue rechazando (422) si se vuelve a forzar la v1
        values = {**values_for(self.definition(self.v1[P124])), "numero_de_bobina": "OTRA-BOBINA"}
        with patch.object(_capture_service, "published_form_version", return_value=self.v1[P124]):
            reply = await self.submit(bobbin["id"], self.body_of(P124, values))
        self.assertEqual(reply.status, 422, reply.text)


def previous_bundle():
    """El bundle de ANTES de MF-06 (P1-24 y P1-25 versión 1, con los campos que se retiran): la v2 más los retirados, sin los añadidos, con su checksum recalculado."""
    forms = []
    for form in BUNDLE.forms:
        if form["code"] in (P124, P125):
            fields = legacy_fields(form["code"])
            for n, f in enumerate(fields, start=1):
                f.setdefault("source", "manual")
                f.setdefault("unit", None)
                f["display_order"] = n
            old = {**form, "version_number": 1, "fields": fields}
            old["definition_checksum"] = compute_definition_checksum(old)
            form = old
        forms.append(form)
    return dataclasses.replace(BUNDLE, source_checksum="d" * 64, forms=tuple(forms))


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción ya tiene la v1 importada: el importador de referencia debe AÑADIR la v2 y dejar la v1 (y todo lo demás) exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf06_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, previous_bundle())

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def snapshot(self, code):
        c = self.connection
        version = c.execute("""SELECT v.id, v.status, v.definition_checksum, v.published_at, v.name FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                               WHERE f.code = %s AND v.version_number = 1""", (code,)).fetchone()
        fields = c.execute("SELECT id, key, label, value_type, required, display_order FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY id", (version[0],)).fetchall()
        return version, fields

    def test_the_new_bundle_adds_version_2_and_leaves_version_1_untouched(self):
        before = {code: self.snapshot(code) for code in (P124, P125)}
        self.assertEqual((len(before[P124][1]), len(before[P125][1])), (12, 14))
        others = self.connection.execute("""SELECT f.code, v.version_number, v.definition_checksum FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                            WHERE f.code <> ALL(%s) ORDER BY f.code, 2""", ([P124, P125],)).fetchall()
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 2)
        self.assertEqual(dry.counts["field"]["create"], 10 + 13)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 4)
        self.assertEqual({code: self.snapshot(code) for code in before}, before, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual({code: self.snapshot(code) for code in before}, before, "las versiones 1 quedan idénticas tras importar las 2")
        for code, count in ((P124, 10), (P125, 13)):
            versions = self.connection.execute("""SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1""", (code,)).fetchall()
            self.assertEqual(versions, [(1, "published"), (2, "published")])
            self.assertEqual(self.connection.execute("""SELECT count(*) FROM vinto_config.field_definition d JOIN vinto_config.form_version v ON v.id = d.form_version_id
                                                        JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = 2""", (code,)).fetchone()[0], count)
        self.assertEqual(self.connection.execute("""SELECT f.code, v.version_number, v.definition_checksum FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                                    WHERE f.code <> ALL(%s) ORDER BY f.code, 2""", ([P124, P125],)).fetchall(), others, "los demás formularios no se tocan")
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="c" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente")


if __name__ == "__main__":
    unittest.main()
