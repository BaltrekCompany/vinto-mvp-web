"""MF-05: VINTO-P1-01 (Operación e inspección de máquina MP3) pasa a la versión 2 SIN el campo «producto_gramaje_crepado» ni «nivel_tanque_t_20».

Se verifica contra PostgreSQL REAL (base efímera *_test) el mecanismo de versionado existente: la versión 1 sigue publicada e intacta (86 campos), la versión 2 del bundle
(84 campos) es la que elige el backend para capturas nuevas, y una captura histórica de la versión 1 sigue siendo legible con su definición original. No se borra ni se
modifica ninguna fila de la versión 1: la versión 2 se AÑADE (es lo que hace el importador de referencia en producción).

MF-09: el bundle trae hoy la versión 3 de P1-01 (sin 11 campos más). Estas pruebas reproducen el estado de producción ENTRE MF-05 y MF-09: la v2 (84 campos) se instala publicada y la v3 se retira solo en la base
efímera de la prueba, de modo que el backend vuelve a elegir la v2. La v3 se prueba en test_mf09_p101_v3_p106_v2.py."""

import contextlib
import dataclasses
import io
import json
import secrets
import unittest
from datetime import datetime, timezone
from pathlib import Path
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
except ModuleNotFoundError:
    from tests.test_assignments_api import call

CODE = "VINTO-P1-01"
REMOVED = ("producto_gramaje_crepado", "nivel_tanque_t_20")
BUNDLE = load_bundle()
CURRENT = next(f for f in BUNDLE.forms if f["code"] == CODE)  # versión vigente del bundle (MF-12A: v4, 70 campos)
# MF-12A: el estado de producción entre MF-09 y MF-12A (v3, 73 campos) sale de una copia fiel de esa definición, no del bundle vigente
FORM = json.loads((Path(__file__).with_name("mf12a_p101_v3.json")).read_text(encoding="utf-8"))
# Los 11 campos que retiró MF-09 (orden de display en la versión 2): (orden, clave, etiqueta, tipo)
RETIRED_BY_MF09 = [(36, "presion_cocedores", "Presión cocedores", "decimal"), (41, "nivel_tanque_h_20_aguas", "Nivel tanque H-20 aguas", "decimal"), (43, "nivel_tanque_h_20_aguas_2", "Nivel tanque H-20 aguas 2", "decimal"),
                   (45, "nivel_tanque_h_20_accionamientos", "Nivel tanque H-20 accionamientos", "decimal"), (46, "opertado", "Opertado", "text"), (47, "produccion", "Producción", "text"),
                   (51, "presion_pope", "Presión pope", "decimal"), (55, "apertura_campana", "Apertura campana", "text"), (56, "presion_regaderas", "Presión regaderas", "decimal"),
                   (76, "limpieza_sala_de_control", "Limpieza sala de control", "text"), (78, "limpieza_mezzanine", "Limpieza mezzanine", "text")]


def v2_fields():
    """Los 84 campos de la versión 2 (MF-05): los 73 del bundle vigente con los 11 retirados por MF-09 en su posición original."""
    fields = [{**f} for f in FORM["fields"]]
    for order, key, label, kind in RETIRED_BY_MF09:
        fields.insert(order - 1, {"key": key, "label": label, "value_type": kind, "source": "manual", "required": True, "unit": None})
    for n, f in enumerate(fields, start=1):
        f["display_order"] = n
    return fields
ARTICLE = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP3")[0]
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf05_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def values_for(fields):
    out = {}
    for n, (key, kind) in enumerate(fields):
        out[key] = f"{n}.25" if kind == "decimal" else ("06:30" if kind == "time" else "dato ficticio MF-05")
    return out


class P101VersionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf05")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        for name in ("JEFATURA", "SUPERVISION", "OPERACION"):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"mf05.{name.lower()}", display_name=name.title(), profile_code=name, password=password, sectors=("BOBINAS",)), password)
        cls.install_v2()
        cls.install_v1()

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def install_v2(cls):
        """Estado de producción tras MF-05: v2 (84 campos) publicada; la versión vigente del bundle (v3, MF-09) se retira para que el backend elija la v2."""
        c = cls.connection
        current = c.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (CODE, CURRENT["version_number"])).fetchone()[0]
        form_id, workflow, area, name = c.execute("SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (current,)).fetchone()
        v2 = c.execute("INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum) VALUES (%s,2,%s,%s,%s,%s) RETURNING id", (form_id, name, area, workflow, "b" * 64)).fetchone()[0]
        for f in v2_fields():
            c.execute("INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order) VALUES (%s,%s,%s,%s,'manual',%s,%s)",
                      (v2, f["key"], f["label"], f["value_type"], f["required"], f["display_order"]))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (v2, current))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (v2,))
        c.execute("UPDATE vinto_config.form_version SET status = 'retired' WHERE id = %s", (current,))
        cls.v2 = v2

    @classmethod
    def install_v1(cls):
        """Reproduce el estado de producción ANTES de importar la v2: la v1 (86 campos, con los dos que se retiran) publicada para las mismas máquinas."""
        c = cls.connection
        form_id, workflow, area, name = c.execute(
            "SELECT form_id, workflow_id, area, name FROM vinto_config.form_version WHERE id = %s", (cls.v2,)).fetchone()
        v1 = c.execute("""INSERT INTO vinto_config.form_version (form_id, version_number, name, area, workflow_id, definition_checksum)
                          VALUES (%s, 1, %s, %s, %s, %s) RETURNING id""", (form_id, name, area, workflow, "a" * 64)).fetchone()[0]
        current = c.execute("SELECT key, label, value_type, required, display_order FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY display_order", (cls.v2,)).fetchall()
        legacy = [("producto_gramaje_crepado", "Producto / gramaje / crepado", "text", True), ("nivel_tanque_t_20", "Nivel tanque T-20", "decimal", True)]
        for order, (key, label, kind, required) in enumerate(legacy + [(k, l, t, r) for k, l, t, r, _o in current], start=1):
            c.execute("""INSERT INTO vinto_config.field_definition (form_version_id, key, label, value_type, source, required, display_order)
                         VALUES (%s,%s,%s,%s,'manual',%s,%s)""", (v1, key, label, kind, required, order))
        c.execute("INSERT INTO vinto_config.form_version_machine (form_version_id, machine_id) SELECT %s, machine_id FROM vinto_config.form_version_machine WHERE form_version_id = %s", (v1, cls.v2))
        c.execute("UPDATE vinto_config.form_version SET status = 'published', published_at = clock_timestamp() WHERE id = %s", (v1,))
        cls.v1 = v1

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
        order = await call("POST", "/api/work-orders", json_body={"machine_code": "MP3", "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE, "quantity": 10, "due_date": "2026-11-01"}]},
                           cookie=await self.cookie("JEFATURA"))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"),
                           json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return reply.json()["assignment"]

    def definition(self, version):
        return self.connection.execute("SELECT key, value_type FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY display_order", (version,)).fetchall()

    async def post(self, assignment, values):
        body = {"capture_id": str(uuid4()), "form_code": CODE, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": values}
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))

    async def test_the_versions_and_the_bundle_match_the_request(self):
        v1, v2 = [k for k, _ in self.definition(self.v1)], [k for k, _ in self.definition(self.v2)]
        self.assertEqual((len(v1), len(v2), FORM["version_number"], len(FORM["fields"])), (86, 84, 3, 73))  # MF-09: el bundle vigente es la v3
        self.assertEqual(sorted(set(v1) - set(v2)), sorted(REMOVED))
        self.assertEqual(set(v2) - set(v1), set())
        self.assertEqual(v2, [f["key"] for f in v2_fields()])
        self.assertEqual(self.connection.execute("SELECT label FROM vinto_config.field_definition WHERE form_version_id = %s AND key = 'nivel_tanque_p17'", (self.v2,)).fetchone()[0], "Nivel tanque PIT")
        for neighbour in ("nivel_tanque_t_30", "nivel_tanque_h_1", "nivel_tanque_h_3", "nivel_tanque_h_20", "nivel_tanque_t_21"):
            self.assertIn(neighbour, v2)
        # el resto de la definición (tipo y obligatoriedad) es idéntico entre versiones
        rest = "SELECT key, value_type, required FROM vinto_config.field_definition WHERE form_version_id = %s AND key <> ALL(%s) ORDER BY key"
        self.assertEqual(self.connection.execute(rest, (self.v1, list(REMOVED))).fetchall(), self.connection.execute(rest, (self.v2, list(REMOVED))).fetchall())

    async def test_history_stays_readable_and_new_captures_use_version_2_without_the_removed_fields(self):
        assignment = await self.assignment()
        # 1) captura HISTÓRICA con la definición original: solo en esta llamada se fuerza la elección de la v1, como ocurría antes de publicar la v2
        #    (una versión publicada es inmutable y no puede retirarse y volver a publicarse: por eso no se manipula su estado)
        with patch.object(_capture_service, "published_form_version", return_value=self.v1):
            old = await self.post(assignment, values_for(self.definition(self.v1)))
        self.assertEqual(old.status, 201, old.text)
        old_capture = old.json()["capture"]
        self.assertEqual(old_capture["form"]["version_number"], 1)
        self.assertEqual(len(old_capture["values"]), 86)
        for key in REMOVED:
            self.assertIn(key, old_capture["values"])
        # 2) captura NUEVA sin los dos campos: el backend la acepta (sin 422) y usa la v2
        new = await self.post(assignment, values_for(self.definition(self.v2)))
        self.assertEqual(new.status, 201, new.text)
        new_capture = new.json()["capture"]
        self.assertEqual(new_capture["form"]["version_number"], 2)
        self.assertEqual(len(new_capture["values"]), 84)
        for key in REMOVED:
            self.assertNotIn(key, new_capture["values"])
        # 3) las dos son accesibles: lectura individual y listado, cada una con SU definición
        for capture in (old_capture, new_capture):
            got = await call("GET", f"/api/captures/{capture['id']}", cookie=await self.cookie("OPERACION"))
            self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        listed = await call("GET", f"/api/captures?form_code={CODE}", cookie=await self.cookie("OPERACION"))
        by_id = {c["id"]: c for c in listed.json()}
        self.assertEqual({by_id[old_capture["id"]]["form"]["version_number"], by_id[new_capture["id"]]["form"]["version_number"]}, {1, 2})
        # 4) PostgreSQL: los valores históricos siguen allí, ligados a la v1
        stored = self.connection.execute("""SELECT f.key FROM vinto_txn.capture_detail d JOIN vinto_config.field_definition f ON f.id = d.field_definition_id
                                           WHERE d.capture_id = %s AND f.key = ANY(%s) ORDER BY f.key""", (old_capture["id"], list(REMOVED))).fetchall()
        self.assertEqual([k for (k,) in stored], sorted(REMOVED))
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (old_capture["id"],)).fetchone()[0], 86)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id = %s", (new_capture["id"],)).fetchone()[0], 84)
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.v1,)).fetchone()[0], 86)

    async def test_the_backend_still_validates_the_version_2_definition(self):
        assignment = await self.assignment()
        good = values_for(self.definition(self.v2))
        # un valor de los campos retirados ya es «campo desconocido» (el frontend nunca lo envía)
        with_old = await self.post(assignment, {**good, "nivel_tanque_t_20": "1.5"})
        self.assertEqual(with_old.status, 422, with_old.text)
        # y un campo obligatorio vigente sigue siendo obligatorio
        missing = {k: v for k, v in good.items() if k != "nivel_tanque_p17"}
        reply = await self.post(assignment, missing)
        self.assertEqual(reply.status, 422, reply.text)
        # ninguno de los dos intentos dejó filas
        self.assertEqual(self.connection.execute("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],)).fetchone()[0], 0)

    async def test_the_offered_form_for_mp3_is_the_published_latest_version(self):
        reply = await call("GET", "/api/production/machines", cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 200, reply.text)
        mp3 = [m for s in reply.json()["sectors"] for m in s["machines"] if m["code"] == "MP3"][0]
        offered = [f for f in mp3["forms"] if f["code"] == CODE]
        self.assertEqual(len(offered), 1, "P1-01 se ofrece una sola vez aunque existan dos versiones publicadas")


def previous_bundle(version=1):
    """El bundle de ANTES de MF-05 (P1-01 versión 1, 86 campos) o el de MF-05 (version=2, 84 campos), con su checksum recalculado."""
    legacy = [{"key": "producto_gramaje_crepado", "label": "Producto / gramaje / crepado", "value_type": "text", "source": "manual", "required": True, "unit": None},
              {"key": "nivel_tanque_t_20", "label": "Nivel tanque T-20", "value_type": "decimal", "source": "manual", "required": True, "unit": None}]
    fields = ([{**f} for f in legacy] if version == 1 else []) + [{**f} for f in v2_fields()]
    for n, f in enumerate(fields, start=1):
        f["display_order"] = n
    old = {**FORM, "version_number": version, "fields": fields}
    old["definition_checksum"] = compute_definition_checksum(old)
    # source_checksum distinto: cada versión del bundle es una fuente distinta (como el manifiesto real antes/después de MF-05)
    return dataclasses.replace(BUNDLE, source_checksum=("d" if version == 1 else "e") * 64, forms=tuple(old if f["code"] == CODE else f for f in BUNDLE.forms))


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción ya tiene la v1 importada: el importador de referencia debe AÑADIR la v2 y dejar la v1 (y todo lo demás) exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf05_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, previous_bundle())
        cls.mf05 = previous_bundle(version=2)

    @classmethod
    def tearDownClass(cls):
        cls.connection.close()
        drop_database(cls.database)

    def snapshot_v1(self):
        c = self.connection
        version = c.execute("""SELECT v.id, v.status, v.definition_checksum, v.published_at, v.name FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                               WHERE f.code = %s AND v.version_number = 1""", (CODE,)).fetchone()
        fields = c.execute("SELECT id, key, label, value_type, required, display_order FROM vinto_config.field_definition WHERE form_version_id = %s ORDER BY id", (version[0],)).fetchall()
        return version, fields

    def test_the_new_bundle_adds_version_2_and_leaves_version_1_untouched(self):
        before = self.snapshot_v1()
        self.assertEqual(len(before[1]), 86)
        others = self.connection.execute("""SELECT f.code, v.version_number, v.definition_checksum FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                            WHERE f.code <> %s ORDER BY f.code""", (CODE,)).fetchall()
        dry = reference.dry_run(self.connection, self.mf05)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"], {"create": 1, "present": 24})
        self.assertEqual(dry.counts["field"]["create"], 84)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 2)
        self.assertEqual(self.snapshot_v1(), before, "el dry-run no escribe")
        result = reference.apply(self.connection, self.mf05)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot_v1(), before, "la versión 1 queda idéntica tras importar la 2")
        versions = self.connection.execute("""SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1""", (CODE,)).fetchall()
        self.assertEqual(versions, [(1, "published"), (2, "published")])
        self.assertEqual(self.connection.execute("""SELECT count(*) FROM vinto_config.field_definition d JOIN vinto_config.form_version v ON v.id = d.form_version_id
                                                    JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = 2""", (CODE,)).fetchone()[0], 84)
        self.assertEqual(self.connection.execute("""SELECT f.code, v.version_number, v.definition_checksum FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id
                                                    WHERE f.code <> %s ORDER BY f.code""", (CODE,)).fetchall(), others, "los otros 24 formularios no se tocan")
        # una segunda importación del mismo bundle es idempotente
        again = reference.apply(self.connection, dataclasses.replace(self.mf05, source_checksum="c" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()))
        self.assertEqual(self.snapshot_v1(), before)


if __name__ == "__main__":
    unittest.main()
