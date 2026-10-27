"""MF-09: VINTO-P1-01 (Operación e inspección de máquina) pasa a la versión 3 SIN 11 campos y VINTO-P1-06 (Registro de control de fardos) a la versión 2 con la opción «toalla».

  - P1-01 v3 (MD_Ejec 10, 12, 13 y 15): se retiran exactamente `presion_cocedores`, `nivel_tanque_h_20_aguas`, `nivel_tanque_h_20_aguas_2`, `nivel_tanque_h_20_accionamientos`, `opertado`, `produccion`,
    `presion_pope`, `apertura_campana`, `presion_regaderas`, `limpieza_sala_de_control` y `limpieza_mezzanine` (84 -> 73 campos). Ningún otro campo cambia.
  - P1-06 v2 (MD_Ejec 18): «Tipo de producto» suma «toalla» como cuarta y última opción; las demás opciones, campos y reglas no cambian.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle; las versiones anteriores (P1-01 v2, P1-06 v1) se instalan aquí como están en producción y siguen publicadas, intactas y legibles."""

import contextlib
import dataclasses
import io
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app.assignments import service as _assignments_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, create_database, database_url, drop_database
from app.seed import reference
from app.seed.bundle import compute_definition_checksum, load_bundle
from migrate import apply as apply_migrations
from migrate import read_migrations

try:
    from test_assignments_api import call
    from test_mf05_p101_v2 import RETIRED_BY_MF09, v2_fields
except ModuleNotFoundError:
    from tests.test_assignments_api import call
    from tests.test_mf05_p101_v2 import RETIRED_BY_MF09, v2_fields

P101, P106 = "VINTO-P1-01", "VINTO-P1-06"
RETIRED = ["presion_cocedores", "nivel_tanque_h_20_aguas", "nivel_tanque_h_20_aguas_2", "nivel_tanque_h_20_accionamientos", "opertado", "produccion", "presion_pope", "apertura_campana",
           "presion_regaderas", "limpieza_sala_de_control", "limpieza_mezzanine"]
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
ARTICLE = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP3")[0]
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}
F6_OK = {"cantidad_fardos": 2, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "3.5"}
F6_V1_OPTIONS = {"punto_merma": [("bobina_rechazada", "Bobina rechazada"), ("recorte_maquina", "Recorte de máquina")],
                 "tipo_producto": [("servilleta", "Servilleta"), ("hoja_doble", "Hoja doble"), ("hoja_simple", "Hoja simple")]}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf09_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def values_for(fields):
    out = {}
    for n, (key, kind) in enumerate(fields):
        out[key] = f"{n}.25" if kind == "decimal" else ("06:30" if kind == "time" else "dato ficticio MF-09")
    return out


class Base(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf09")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name in ("JEFATURA", "SUPERVISION", "OPERACION"):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"mf09.{name.lower()}", display_name=name.title(), profile_code=name, password=password, sectors=("BOBINAS",)), password)
        cls.current = {code: cls.version(code, FORMS[code]["version_number"]) for code in (P101, P106)}
        cls.old = {}
        cls.install_old(P101, 2, [(f["key"], f["label"], f["value_type"], f["required"]) for f in v2_fields()], {})
        f6 = FORMS[P106]
        cls.install_old(P106, 1, [(f["key"], f["label"], f["value_type"], f["required"]) for f in f6["fields"]], F6_V1_OPTIONS)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def version(cls, code, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()[0]

    @classmethod
    def install_old(cls, code, number, fields, options):
        """Versión HISTÓRICA publicada como en producción antes de MF-09; el backend sigue eligiendo la más alta (la del bundle)."""
        c = cls.connection
        form_id, workflow, area, name = c.execute("SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (cls.current[code],)).fetchone()
        old = c.execute("INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s,%s,%s,%s,%s,%s) RETURNING id", (form_id, number, name, area, workflow, "a" * 64)).fetchone()[0]
        unit = {r[0]: r[1] for r in c.execute("SELECT key, unit_id FROM vinto_config.field_definition WHERE form_version_id = %s", (cls.current[code],)).fetchall()}
        for order, (key, label, kind, required) in enumerate(fields, start=1):
            fid = c.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, unit_id, display_order) VALUES (%s,%s,%s,%s,'manual',%s,%s,%s) RETURNING id", (old, key, label, kind, required, unit.get(key), order)).fetchone()[0]
            for n, (option, option_label) in enumerate(options.get(key, []), start=1):
                c.execute("INSERT INTO vinto_config.field_option (form_version_id, field_definition_id, option_key, label, display_order) VALUES (%s,%s,%s,%s,%s)", (old, fid, option, option_label, n))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (old, cls.current[code]))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (old,))
        cls.old[(code, number)] = old

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        for target in (_capture_service, _assignments_service):
            p = patch.object(target, "_now", return_value=DAY)
            p.start()
            self.addCleanup(p.stop)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def assignment(self):
        order = await call("POST", "/api/work-orders", json_body={"machine_code": "MP3", "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE, "quantity": 10, "due_date": "2026-11-01"}]}, cookie=await self.cookie("JEFATURA"))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return reply.json()["assignment"]

    def definition(self, version):
        return [tuple(r) for r in self.connection.execute("SELECT key, value_type FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY display_order", (version,)).fetchall()]

    async def post(self, assignment, code, values, old=None):
        body = {"capture_id": str(uuid4()), "form_code": code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": values}
        if old is None:
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        with patch.object(_capture_service, "published_form_version", return_value=self.old[old]):  # solo aquí se fuerza la versión anterior, como antes de publicar la nueva
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def count(self, assignment):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],))


class DefinitionTests(Base):
    async def test_bundle_versions_and_scope(self):
        self.assertEqual((FORMS[P101]["version_number"], FORMS[P106]["version_number"]), (3, 2))
        self.assertEqual(sorted((f["code"], f["version_number"]) for f in BUNDLE.forms if f["version_number"] != 1),
                         [(P101, 3), (P106, 2), ("VINTO-P1-18", 2), ("VINTO-P1-21", 2), ("VINTO-P1-22", 2), ("VINTO-P1-24", 3), ("VINTO-P1-25", 3), ("VINTO-P1-26", 2)], "ningún otro formulario cambia")
        for code in (P101, P106):
            self.assertEqual(FORMS[code]["machines"], ["MP1", "MP3"])
            self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.current[code],)), "published")

    async def test_p1_01_v3_drops_exactly_the_eleven_approved_fields(self):
        self.assertEqual(sorted(k for _o, k, _l, _t in RETIRED_BY_MF09), sorted(RETIRED), "lista autorizada")
        v2, v3 = self.definition(self.old[(P101, 2)]), self.definition(self.current[P101])
        self.assertEqual((len(v2), len(v3)), (84, 73))
        self.assertEqual([k for k, _ in v3], [k for k, _ in v2 if k not in RETIRED], "mismo orden y mismas claves, solo sin los 11")
        self.assertEqual(sorted(set(k for k, _ in v2) - set(k for k, _ in v3)), sorted(RETIRED))
        for key in RETIRED:
            self.assertNotIn(key, [k for k, _ in v3])
        rest = "SELECT key, label, value_type, required, unit_id FROM vinto_config.field_definition WHERE form_version_id = %s AND key <> ALL(%s) ORDER BY key"
        self.assertEqual(self.connection.execute(rest, (self.old[(P101, 2)], RETIRED)).fetchall(), self.connection.execute(rest, (self.current[P101], RETIRED)).fetchall(), "etiquetas, tipos, obligatoriedad y unidades idénticos")
        for neighbour in ("nivel_tanque_t_30_aguas", "nivel_tanque_t_30_accionamientos", "limpieza", "limpieza_escalera", "limpieza_lado_transmision", "apertura_purga_prensa", "vacio_tela"):
            self.assertIn(neighbour, [k for k, _ in v3], "no se retira ningún campo adicional")

    async def test_p1_06_v2_only_adds_the_fourth_option(self):
        new, old = self.current[P106], self.old[(P106, 1)]
        q = "SELECT key, label, value_type, required, unit_id, display_order FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY display_order"
        self.assertEqual(self.connection.execute(q, (new,)).fetchall(), self.connection.execute(q, (old,)).fetchall(), "campos idénticos")
        opts = lambda v: self.connection.execute("""SELECT f.key, o.option_key, o.label, o.display_order FROM vinto_config.field_option o JOIN vinto_config.field_definition f ON f.id = o.field_definition_id
                                                    WHERE o.form_version_id = %s ORDER BY f.display_order, o.display_order""", (v,)).fetchall()
        new_opts, old_opts = opts(new), opts(old)
        self.assertEqual(new_opts[:-1], old_opts, "las tres opciones anteriores conservan clave, etiqueta y orden")
        self.assertEqual(new_opts[-1], ("tipo_producto", "toalla", "Toalla", 4), "Toalla es la cuarta y última opción")
        self.assertEqual([o[1] for o in new_opts if o[0] == "tipo_producto"], ["servilleta", "hoja_doble", "hoja_simple", "toalla"])


class P101Tests(Base):
    async def test_v3_capture_is_saved_without_the_retired_fields(self):
        assignment = await self.assignment()
        reply = await self.post(assignment, P101, values_for(self.definition(self.current[P101])))
        self.assertEqual(reply.status, 201, reply.text)
        capture = reply.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], len(capture["values"])), (3, 73))
        for key in RETIRED:
            self.assertNotIn(key, capture["values"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (capture["id"],)), 73)

    async def test_each_retired_key_is_rejected_as_unknown_and_nothing_is_saved(self):
        assignment = await self.assignment()
        good = values_for(self.definition(self.current[P101]))
        for key in RETIRED:
            reply = await self.post(assignment, P101, {**good, key: "1.5"})
            self.assertEqual(reply.status, 422, (key, reply.text))
            self.assertIn(key, reply.text)
        self.assertEqual(self.count(assignment), 0)

    async def test_remaining_fields_keep_their_obligatoriness(self):
        assignment = await self.assignment()
        good = values_for(self.definition(self.current[P101]))
        for key in ("nivel_tanque_p17", "nivel_tanque_t_30_aguas", "limpieza", "limpieza_escalera", "limpieza_lado_transmision", "novedades", "hora_cambio_cuchilla_de_cambio"):
            reply = await self.post(assignment, P101, {k: v for k, v in good.items() if k != key})
            self.assertEqual(reply.status, 422, key)
            self.assertIn(key, reply.text)
        self.assertEqual(self.count(assignment), 0)
        self.assertEqual((await self.post(assignment, P101, good)).status, 201)

    async def test_versions_1_and_2_history_stays_readable_with_the_retired_values(self):
        assignment = await self.assignment()
        old = await self.post(assignment, P101, values_for(self.definition(self.old[(P101, 2)])), old=(P101, 2))
        self.assertEqual(old.status, 201, old.text)
        old_capture = old.json()["capture"]
        self.assertEqual((old_capture["form"]["version_number"], len(old_capture["values"])), (2, 84))
        for key in RETIRED:
            self.assertIn(key, old_capture["values"], "los valores históricos se conservan")
        new = await self.post(assignment, P101, values_for(self.definition(self.current[P101])))
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 3)
        for capture in (old_capture, new.json()["capture"]):
            got = await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))
            self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        listed = (await call("GET", f"/api/captures?form_code={P101}", cookie=await self.cookie("OPERACION"))).json()
        self.assertEqual({c["form"]["version_number"] for c in listed if c["id"] in (old_capture["id"], new.json()["capture"]["id"])}, {2, 3})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (old_capture["id"],)), 84)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[(P101, 2)],)), 84)

    async def test_the_form_is_offered_once_for_mp3(self):
        reply = await call("GET", "/api/production/machines", cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 200, reply.text)
        for machine in ("MP1", "MP3"):
            m = [m for s in reply.json()["sectors"] for m in s["machines"] if m["code"] == machine][0]
            self.assertEqual(len([f for f in m["forms"] if f["code"] in (P101, P106)]), 2, machine)


class P106Tests(Base):
    async def test_toalla_and_the_three_previous_options_are_accepted_and_saved(self):
        assignment = await self.assignment()
        for option in ("servilleta", "hoja_doble", "hoja_simple", "toalla"):
            reply = await self.post(assignment, P106, {**F6_OK, "tipo_producto": option})
            self.assertEqual(reply.status, 201, (option, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual((capture["form"]["version_number"], capture["values"]["tipo_producto"]), (2, option))
            self.assertEqual(self.scalar("SELECT d.value_text FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND f.key = 'tipo_producto'", (capture["id"],)), option)

    async def test_unknown_options_are_still_rejected(self):
        assignment = await self.assignment()
        for bad in ("Toalla", "TOALLA", "carton", "cartón", "hoja", "Hoja doble", "", None, 4, ["toalla"]):
            reply = await self.post(assignment, P106, {**F6_OK, "tipo_producto": bad})
            self.assertEqual(reply.status, 422, repr(bad))
        self.assertEqual((await self.post(assignment, P106, {**F6_OK, "punto_merma": "otro"})).status, 422)
        self.assertEqual((await self.post(assignment, P106, {k: v for k, v in F6_OK.items() if k != "peso_kg"})).status, 422, "el resto de las reglas no cambia")
        self.assertEqual(self.count(assignment), 0)

    async def test_version_1_history_keeps_its_original_values_and_definition(self):
        assignment = await self.assignment()
        old = await self.post(assignment, P106, {**F6_OK, "tipo_producto": "hoja_simple"}, old=(P106, 1))
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual((capture["form"]["version_number"], capture["values"]["tipo_producto"]), (1, "hoja_simple"))
        # con la definición v1 «toalla» no existe: no se reinterpreta nada de lo anterior
        rejected = await self.post(assignment, P106, {**F6_OK, "tipo_producto": "toalla"}, old=(P106, 1))
        self.assertEqual(rejected.status, 422, rejected.text)
        new = await self.post(assignment, P106, {**F6_OK, "tipo_producto": "toalla"})
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 2)
        got = await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))
        self.assertEqual((got.status, got.json()["values"]["tipo_producto"]), (200, "hoja_simple"))
        listed = (await call("GET", f"/api/captures?form_code={P106}", cookie=await self.cookie("OPERACION"))).json()
        self.assertEqual({c["form"]["version_number"] for c in listed if c["id"] in (capture["id"], new.json()["capture"]["id"])}, {1, 2})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_option WHERE form_version_id = %s", (self.old[(P106, 1)],)), 5, "la v1 conserva sus 5 opciones")

    async def test_nothing_else_is_created_by_a_fardos_capture(self):
        assignment = await self.assignment()
        before = [self.scalar(f"SELECT count(*) FROM vinto_txn.{t}") for t in ("bobbin", "work_order", "assignment")]
        self.assertEqual((await self.post(assignment, P106, {**F6_OK, "tipo_producto": "toalla"})).status, 201)
        self.assertEqual([self.scalar(f"SELECT count(*) FROM vinto_txn.{t}") for t in ("bobbin", "work_order", "assignment")], before, "no se crean bobinas, OT ni asignaciones")


def variant(checksum, spec):
    """El bundle vigente con algunas versiones de formulario sustituidas: {código: (versión, campos, opciones)}. Reproduce el estado de producción antes de MF-09."""
    forms = []
    for form in BUNDLE.forms:
        if form["code"] in spec:
            number, fields, options = spec[form["code"]]
            built = []
            for n, f in enumerate(fields, start=1):
                item = {"source": "manual", "unit": None, **{k: v for k, v in f.items() if k != "options"}, "display_order": n}
                if options.get(f["key"]):
                    item["options"] = [{"option_key": o, "label": lbl, "display_order": i} for i, (o, lbl) in enumerate(options[f["key"]], start=1)]
                built.append(item)
            form = {**form, "version_number": number, "fields": built}
            form["definition_checksum"] = compute_definition_checksum(form)
        forms.append(form)
    return dataclasses.replace(BUNDLE, source_checksum=checksum, forms=tuple(forms))


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción tiene P1-01 v1 y v2 y P1-06 v1: el importador debe AÑADIR P1-01 v3 y P1-06 v2 y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf09_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        v2 = [{k: f[k] for k in ("key", "label", "value_type", "required", "unit")} for f in v2_fields()]
        legacy = [{"key": "producto_gramaje_crepado", "label": "Producto / gramaje / crepado", "value_type": "text", "required": True, "unit": None},
                  {"key": "nivel_tanque_t_20", "label": "Nivel tanque T-20", "value_type": "decimal", "required": True, "unit": None}]
        f6_v1 = [{k: f[k] for k in ("key", "label", "value_type", "required", "unit")} for f in FORMS[P106]["fields"]]
        opts_v1 = F6_V1_OPTIONS
        reference.apply(cls.connection, variant("1" * 64, {P101: (1, legacy + v2, {}), P106: (1, f6_v1, opts_v1)}))
        reference.apply(cls.connection, variant("2" * 64, {P101: (2, v2, {}), P106: (1, f6_v1, opts_v1)}))

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
        options = c.execute(f"""SELECT f.code, v.version_number, o.option_key, o.label, o.display_order FROM vinto_config.field_option o JOIN vinto_config.form_version v ON v.id = o.form_version_id
                                JOIN vinto_config.form f ON f.id = v.form_id WHERE {where} ORDER BY 1, 2, 5""").fetchall()
        return versions, fields, options

    def test_the_bundle_adds_only_the_new_versions_and_is_idempotent(self):
        old_where = f"(f.code = '{P101}' AND v.version_number IN (1, 2)) OR (f.code = '{P106}' AND v.version_number = 1)"
        other_where = f"f.code NOT IN ('{P101}','{P106}')"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual((len(old[0]), len(old[1]), len(old[2])), (3, 86 + 84 + 5, 5))
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 2)
        self.assertEqual(dry.counts["field"]["create"], 73 + 5)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 4)
        self.assertEqual(dry.counts["option"]["create"], 6)
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "las versiones anteriores, sus campos y opciones quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        self.assertEqual(self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (P101,)).fetchall(),
                         [(1, "published"), (2, "published"), (3, "published")])
        self.assertEqual(self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (P106,)).fetchall(),
                         [(1, "published"), (2, "published")])
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")


if __name__ == "__main__":
    unittest.main()
