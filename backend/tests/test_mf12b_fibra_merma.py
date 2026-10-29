"""MF-12B: VINTO-P1-04 versión 2 (consumo de fibra, MD_Ejec 17) y VINTO-P1-16 versión 3 (control de merma, MD_Ejec 44).

  - P1-04 v2 (MP1 y MP3): UNA captura por consumo: hora_consumo, material, origen (según el material), presentacion (según el material), cantidad_um (entero), peso_unitario_real (decimal, kg) y observaciones.
    El subtotal NO es un campo. Los valores de las listas son los TEXTOS literales del MVP anterior. La combinación material-origen / material-presentación se valida en el backend SOLO desde la versión 2.
  - P1-16 v3 (11 máquinas): UNA pesada por captura: hora_inicio y hora_fin (MF-11), numero_correlativo (manual), tipo_merma (6 opciones), origen_merma (3), peso_merma_kg (decimal, kg) y observacion.
    Las seis cantidades de las versiones 1 y 2 no existen en la v3 y sus capturas no se convierten en pesadas.

Se verifica contra PostgreSQL REAL (base efímera *_test) con los formularios REALES del bundle; las versiones anteriores (P1-04 v1, P1-16 v2) se instalan aquí como están en producción y siguen publicadas, intactas y legibles."""

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
from app import dependent_options
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

P104, P116 = "VINTO-P1-04", "VINTO-P1-16"
NEW_VERSION = {P104: 2, P116: 3}
HERE = Path(__file__).parent
PREVIOUS = {P104: json.loads((HERE / "mf12b_p104_v1.json").read_text(encoding="utf-8")), P116: json.loads((HERE / "mf12b_p116_v2.json").read_text(encoding="utf-8"))}
BUNDLE = load_bundle()
FORMS = {f["code"]: f for f in BUNDLE.forms}
ARTICLE = {m: sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == m)[0] for m in {r["machine_code"] for r in BUNDLE.article_machines}}
SECTORS = ("BOBINAS", "REBOBINADO", "CONVERSION")
DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
STATE = {}
MATERIALS = {"Fibra larga": ("Laja", "Susano", "Dorado"), "Fibra corta": ("Laja", "Cóndor"), "Recorte": ("Sauce Rancho", "Máquina")}
PRESENTATIONS = {"Fibra larga": ("Caja", "Fardo"), "Fibra corta": ("Caja", "Fardo"), "Recorte": ("Fardo",)}
TIPOS = ["Hoja doble", "Hoja simple", "Servilleta", "Toalla", "Cartón", "Plástico"]
ORIGENES = ["Logs", "Cola", "Máquina"]
SIX = ("hoja_doble_kg", "servilleta_kg", "toalla_kg", "carton_kg", "hoja_simple_kg", "plastico_kg")
OLD_104 = ("fibra_corta_detalle", "fibra_larga_detalle", "recorte_ph", "recorte_servilleta", "recorte_toalla", "materia_prima_ph", "materia_prima_servilleta", "materia_prima_toalla")


def setUpModule():
    STATE["template"] = build_reference_template("vinto_mf12b_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def variant(checksum, spec):
    """El bundle vigente con algunos formularios sustituidos por su versión anterior (tal como está publicada en producción)."""
    forms = [PREVIOUS[f["code"]] if f["code"] in spec else f for f in BUNDLE.forms]
    return dataclasses.replace(BUNDLE, source_checksum=checksum, forms=tuple(forms))


def v104(**extra):
    return {"hora_consumo": "07:30", "material": "Fibra larga", "origen": "Laja", "presentacion": "Caja", "cantidad_um": 12, "peso_unitario_real": "25.5", **extra}


def v116(**extra):
    return {"hora_inicio": "06:30", "hora_fin": "14:45", "numero_correlativo": "M-0001", "tipo_merma": "Hoja doble", "origen_merma": "Logs", "peso_merma_kg": "12.5", **extra}


def without(values, *keys):
    return {k: v for k, v in values.items() if k not in keys}


class DefinitionTests(unittest.TestCase):
    def test_only_the_two_forms_get_a_new_version(self):
        self.assertEqual(FORMS[P104]["version_number"], 2)
        self.assertEqual(FORMS[P116]["version_number"], 3)
        self.assertEqual(sorted(FORMS[P104]["machines"]), ["MP1", "MP3"], "P1-04 sigue en MP1 y MP3")
        self.assertEqual(len(FORMS[P116]["machines"]), 11)
        self.assertEqual(sorted(FORMS[P116]["machines"]), sorted(PREVIOUS[P116]["machines"]), "P1-16 conserva sus 11 máquinas")
        self.assertEqual({c: FORMS[c]["version_number"] for c in ("VINTO-P1-01", "VINTO-P1-05", "VINTO-P1-31", "VINTO-P1-11", "VINTO-P1-12", "VINTO-P1-13")},
                         {"VINTO-P1-01": 4, "VINTO-P1-05": 2, "VINTO-P1-31": 2, "VINTO-P1-11": 2, "VINTO-P1-12": 3, "VINTO-P1-13": 2}, "MF-11 y MF-12A siguen igual")
        self.assertEqual(sum(len(f["fields"]) + sum(len(g["fields"]) for g in f["groups"]) for f in BUNDLE.forms), 464)

    def test_p1_04_v2_fields_and_literal_catalogs(self):
        fields = FORMS[P104]["fields"]
        self.assertEqual([(f["key"], f["label"], f["value_type"], f["required"], f["unit"]) for f in fields], [
            ("hora_consumo", "Hora de consumo", "time", True, None), ("material", "Material", "text", True, None), ("origen", "Origen", "text", True, None),
            ("presentacion", "Presentación", "text", True, None), ("cantidad_um", "Cantidad de UM", "integer", True, None), ("peso_unitario_real", "Peso unitario real", "decimal", True, "KG"),
            ("observaciones", "Observaciones", "textarea", False, None)])
        by = {f["key"]: f for f in fields}
        self.assertEqual([o["option_key"] for o in by["material"]["options"]], list(MATERIALS))
        self.assertEqual([o["option_key"] for o in by["origen"]["options"]], ["Laja", "Susano", "Dorado", "Cóndor", "Sauce Rancho", "Máquina"])
        self.assertEqual([o["option_key"] for o in by["presentacion"]["options"]], ["Caja", "Fardo"])
        for key in ("material", "origen", "presentacion"):
            self.assertTrue(all(o["option_key"] == o["label"] for o in by[key]["options"]), f"{key}: el valor guardado es el texto literal, no una clave técnica")
        self.assertFalse([f for f in fields if "subtotal" in f["key"] or "total" in f["key"]], "el subtotal no se persiste")
        self.assertTrue(all(f["source"] == "manual" for f in fields))

    def test_the_backend_rules_match_the_options_published_in_the_seed(self):
        by = {f["key"]: f for f in FORMS[P104]["fields"]}
        self.assertEqual(dependent_options.MATERIAL_ORIGENES, MATERIALS)
        self.assertEqual(dependent_options.MATERIAL_PRESENTACIONES, PRESENTATIONS)
        self.assertEqual(sorted({o for v in MATERIALS.values() for o in v}), sorted(o["option_key"] for o in by["origen"]["options"]), "la unión de los orígenes permitidos es la lista publicada")
        self.assertEqual(sorted({o for v in PRESENTATIONS.values() for o in v}), sorted(o["option_key"] for o in by["presentacion"]["options"]))
        self.assertEqual(sorted(MATERIALS), sorted(o["option_key"] for o in by["material"]["options"]))
        self.assertEqual(dependent_options.RULES["VINTO-P1-04"][0], 2, "solo desde la versión 2")
        self.assertEqual(list(dependent_options.RULES), ["VINTO-P1-04"], "ningún otro formulario tiene reglas dependientes")

    def test_p1_04_v1_is_the_nine_original_fields(self):
        self.assertEqual([f["key"] for f in PREVIOUS[P104]["fields"]], [*OLD_104, "observaciones"])

    def test_p1_16_v3_fields_and_options(self):
        fields = FORMS[P116]["fields"]
        self.assertEqual([(f["key"], f["label"], f["value_type"], f["required"], f["unit"]) for f in fields], [
            ("hora_inicio", "Hora inicio", "time", True, None), ("hora_fin", "Hora fin", "time", True, None), ("numero_correlativo", "Número correlativo", "text", True, None),
            ("tipo_merma", "Tipo de merma", "text", True, None), ("origen_merma", "Origen de la merma", "text", True, None), ("peso_merma_kg", "Peso real", "decimal", True, "KG"),
            ("observacion", "Observación", "textarea", False, None)])
        by = {f["key"]: f for f in fields}
        self.assertEqual([o["option_key"] for o in by["tipo_merma"]["options"]], TIPOS)
        self.assertEqual([o["option_key"] for o in by["origen_merma"]["options"]], ORIGENES)
        self.assertTrue(all(o["option_key"] == o["label"] for k in ("tipo_merma", "origen_merma") for o in by[k]["options"]))
        self.assertFalse([f for f in fields if f["key"] in SIX], "las seis cantidades de las versiones 1 y 2 no existen en la v3")
        self.assertEqual([f["key"] for f in PREVIOUS[P116]["fields"]], ["hora_inicio", "hora_fin", "numero_correlativo", *SIX, "observacion"])
        # el correlativo sigue siendo manual: un campo de texto obligatorio sin numeración automática
        self.assertEqual((by["numero_correlativo"]["value_type"], by["numero_correlativo"]["source"]), ("text", "manual"))

    def test_the_dependency_check_in_isolation(self):
        ok = {"material": "Recorte", "origen": "Máquina", "presentacion": "Fardo"}
        self.assertEqual(dependent_options.check(P104, 2, ok), [])
        self.assertEqual(dependent_options.check(P104, 2, {**ok, "presentacion": "Caja"}), ["presentacion: no corresponde al valor elegido en material"])
        self.assertEqual(dependent_options.check(P104, 2, {"material": "Fibra corta", "origen": "Susano", "presentacion": "Caja"}), ["origen: no corresponde al valor elegido en material"])
        self.assertEqual(dependent_options.check(P104, 1, {"material": "Recorte", "origen": "Laja", "presentacion": "Caja"}), [], "la versión 1 no se valida")
        self.assertEqual(dependent_options.check("VINTO-P1-12", 3, {"material": "Recorte", "origen": "Laja"}), [], "otro formulario no se valida")
        self.assertEqual(dependent_options.check(P104, 2, {"origen": "Laja"}), [], "lo ausente lo informa la definición")
        for problem in dependent_options.check(P104, 2, {"material": "Recorte", "origen": "ZZ-secreto", "presentacion": "Caja"}):
            self.assertNotIn("ZZ-secreto", problem, "nunca se devuelve el valor recibido")


class Base(unittest.IsolatedAsyncioTestCase):
    """Producción central con asignación sobre una base efímera: bundle vigente + las versiones anteriores publicadas como en producción."""

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_mf12b")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        with contextlib.redirect_stdout(io.StringIO()):
            reference.apply(cls.connection, variant("7" * 64, NEW_VERSION))  # P1-04 v1 y P1-16 v2 publicadas como en producción (aditivo)
        cls.old = {code: cls.version(code, NEW_VERSION[code] - 1) for code in NEW_VERSION}
        cls.new = {code: cls.version(code, NEW_VERSION[code]) for code in NEW_VERSION}
        cls.users, cls.cookies = {}, {}
        for name, profile, sectors in (("JEFATURA", "JEFATURA", SECTORS), ("SUPERVISION", "SUPERVISION", SECTORS), ("OPERACION", "OPERACION", SECTORS), ("CALIDAD", "CALIDAD", ("BOBINAS",)), ("SIN_SECTOR", "OPERACION", ())):
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[name] = (create_user(cls.connection, username=f"mf12b.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors), password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    @classmethod
    def version(cls, code, number):
        return cls.connection.execute("SELECT v.id FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s AND v.version_number = %s", (code, number)).fetchone()[0]

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

    async def assignment(self, machine):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        order = await call("POST", "/api/work-orders", json_body={"machine_code": machine, "lines": [{"pv_reference": "PV-1", "article_code": ARTICLE[machine], "quantity": 10, "due_date": "2026-11-01"}]}, cookie=await self.cookie("JEFATURA"))
        self.assertEqual(order.status, 201, order.text)
        order = (await call("POST", f"/api/work-orders/{order.json()['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201, reply.text)
        return reply.json()["assignment"]

    async def post(self, assignment, code, values, old=False, capture_id=None, who="OPERACION"):
        body = {"capture_id": capture_id or str(uuid4()), "form_code": code, "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": values}
        if not old:
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who)), body
        with patch.object(_capture_service, "published_form_version", return_value=self.old[code]):  # solo aquí se fuerza la versión anterior, como antes de publicar la nueva
            return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(who)), body

    async def get(self, capture_id):
        return await call("GET", f"/api/captures/{capture_id}", cookie=await self.cookie("OPERACION"))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]

    def count(self, assignment):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],))

    def stored(self, capture_id):
        return {k: (t, v) for k, t, v in self.connection.execute(
            """SELECT f.key, d.value_type, coalesce(d.value_decimal::text, d.value_integer::text, d.value_time::text, d.value_text) FROM vinto_txn.capture_detail d
               JOIN vinto_config.field_definition f ON f.id = d.field_definition_id WHERE d.capture_id = %s AND d.group_row_id IS NULL""", (capture_id,)).fetchall()}


class P104Tests(Base):
    async def test_a_valid_consumption_is_one_capture_with_literal_texts_and_no_subtotal(self):
        for machine in ("MP1", "MP3"):
            assignment = await self.assignment(machine)
            reply, _ = await self.post(assignment, P104, v104(observaciones="lote nuevo"))
            self.assertEqual(reply.status, 201, (machine, reply.text))
            capture = reply.json()["capture"]
            self.assertEqual(capture["form"]["version_number"], 2)
            self.assertEqual(capture["values"], {"hora_consumo": "07:30:00", "material": "Fibra larga", "origen": "Laja", "presentacion": "Caja", "cantidad_um": 12, "peso_unitario_real": "25.5", "observaciones": "lote nuevo"})
            stored = self.stored(capture["id"])
            self.assertEqual((stored["material"], stored["origen"], stored["presentacion"]), (("text", "Fibra larga"), ("text", "Laja"), ("text", "Caja")), "texto literal, sin claves técnicas")
            self.assertEqual(stored["cantidad_um"][0], "integer")
            self.assertEqual(stored["peso_unitario_real"], ("decimal", "25.5"))
            self.assertFalse([k for k in stored if "subtotal" in k or "total" in k], "el subtotal no se guarda")
            self.assertFalse([k for k in capture["values"] if "subtotal" in k])
            got = await self.get(capture["id"])
            self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))

    async def test_every_valid_combination_is_accepted_and_each_consumption_is_its_own_capture(self):
        assignment = await self.assignment("MP1")
        n = 0
        for material, origins in MATERIALS.items():
            for origin in origins:
                for presentation in PRESENTATIONS[material]:
                    reply, _ = await self.post(assignment, P104, v104(material=material, origen=origin, presentacion=presentation))
                    self.assertEqual(reply.status, 201, (material, origin, presentation, reply.text))
                    n += 1
        self.assertEqual(n, 3 * 2 + 2 * 2 + 2 * 1)
        self.assertEqual(self.count(assignment), n, "una captura por consumo: ninguna sustituye a otra")
        self.assertEqual(self.scalar("SELECT count(DISTINCT id) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment["id"],)), n)

    async def test_the_backend_rejects_invalid_material_origin_and_material_presentation_pairs(self):
        assignment = await self.assignment("MP3")
        n = self.count(assignment)
        invalid = [(m, o, p) for m in MATERIALS for o in ("Laja", "Susano", "Dorado", "Cóndor", "Sauce Rancho", "Máquina") if o not in MATERIALS[m] for p in PRESENTATIONS[m]]
        invalid += [(m, o, p) for m in MATERIALS for o in MATERIALS[m] for p in ("Caja", "Fardo") if p not in PRESENTATIONS[m]]
        self.assertTrue(invalid)
        for material, origin, presentation in invalid:
            reply, _ = await self.post(assignment, P104, v104(material=material, origen=origin, presentacion=presentation))
            self.assertEqual(reply.status, 422, (material, origin, presentation))
            self.assertIn("no corresponde al valor elegido en material", reply.text)
        self.assertEqual(self.count(assignment), n, "los rechazos no dejaron filas")
        reply, _ = await self.post(assignment, P104, v104(material="Recorte", origen="Laja", presentacion="Caja"))
        self.assertIn("origen", reply.text)
        self.assertIn("presentacion", reply.text)
        self.assertNotIn("Recorte", reply.text, "el mensaje no devuelve los valores recibidos")

    async def test_lists_are_closed_and_literal(self):
        assignment = await self.assignment("MP1")
        for key, bad in (("material", "Papel"), ("material", "fibra larga"), ("material", "FIBRA LARGA"), ("origen", "Otro"), ("origen", "laja"), ("presentacion", "Bolsa"), ("presentacion", "caja")):
            reply, _ = await self.post(assignment, P104, v104(**{key: bad}))
            self.assertEqual(reply.status, 422, (key, bad))
            self.assertIn(key, reply.text)

    async def test_required_fields_types_and_unknown_keys(self):
        assignment = await self.assignment("MP1")
        good = v104()
        for key in ("hora_consumo", "material", "origen", "presentacion", "cantidad_um", "peso_unitario_real"):
            reply, _ = await self.post(assignment, P104, without(good, key))
            self.assertEqual(reply.status, 422, key)
            self.assertIn(key, reply.text)
        self.assertEqual((await self.post(assignment, P104, without(good, "observaciones")))[0].status, 201, "las observaciones son opcionales")
        for bad in ("24:00", "12:60", "7:30", "abc", "", None):
            self.assertEqual((await self.post(assignment, P104, v104(hora_consumo=bad)))[0].status, 422, f"hora {bad!r}")
        for ok in ("00:00", "23:59"):
            self.assertEqual((await self.post(assignment, P104, v104(hora_consumo=ok)))[0].status, 201, ok)
        for bad in (1.5, "1.5", "abc", True, None):
            self.assertEqual((await self.post(assignment, P104, v104(cantidad_um=bad)))[0].status, 422, f"cantidad {bad!r}")
        for ok in (0, 1, 250, "7"):
            self.assertEqual((await self.post(assignment, P104, v104(cantidad_um=ok)))[0].status, 201, f"cantidad {ok!r}")
        for bad in ("abc", "1e3", "12 kg", True):
            self.assertEqual((await self.post(assignment, P104, v104(peso_unitario_real=bad)))[0].status, 422, f"peso {bad!r}")
        for ok in ("0.5", "25", "1000.125", 3):
            self.assertEqual((await self.post(assignment, P104, v104(peso_unitario_real=ok)))[0].status, 201, f"peso {ok!r}")
        for key in ("subtotal", "subtotal_kg", "total_kg", *OLD_104):
            reply, _ = await self.post(assignment, P104, {**good, key: "1"})
            self.assertEqual(reply.status, 422, key)
            self.assertIn("campo desconocido", reply.text)

    async def test_idempotent_retry_of_the_same_consumption(self):
        assignment = await self.assignment("MP1")
        first, body = await self.post(assignment, P104, v104())
        self.assertEqual(first.status, 201)
        again = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
        self.assertEqual(again.status, 200)
        self.assertEqual(again.json()["capture"]["id"], first.json()["capture"]["id"])
        self.assertEqual(self.count(assignment), 1)
        other = await call("POST", "/api/captures", json_body={**body, "values": v104(cantidad_um=13)}, cookie=await self.cookie("OPERACION"))
        self.assertEqual(other.status, 409, "el mismo capture_id con otros valores es un conflicto")

    async def test_authorization_is_unchanged(self):
        assignment = await self.assignment("MP1")
        reply, _ = await self.post(assignment, P104, v104(), who="CALIDAD")
        self.assertEqual(reply.status, 403, "el perfil de Calidad no captura producción")
        reply, _ = await self.post(assignment, P104, v104(), who="SIN_SECTOR")
        self.assertIn(reply.status, (403, 404), "sin sector Bobinas no se alcanza el formulario")
        self.assertEqual(self.count(assignment), 0)

    async def test_the_historic_version_1_stays_readable_and_does_not_use_the_new_rules(self):
        assignment = await self.assignment("MP1")
        old_values = {"fibra_corta_detalle": "corta", "fibra_larga_detalle": "larga", "recorte_ph": "12.5", "recorte_servilleta": "3 bultos", "recorte_toalla": "2",
                      "materia_prima_ph": "340", "materia_prima_servilleta": "10", "materia_prima_toalla": "7", "observaciones": "ok"}
        old, _ = await self.post(assignment, P104, old_values, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual(capture["form"]["version_number"], 1)
        self.assertEqual(capture["values"], old_values, "valores originales intactos")
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        for key in ("hora_consumo", "material", "origen", "presentacion", "cantidad_um", "peso_unitario_real"):
            reply, _ = await self.post(assignment, P104, {**old_values, key: "x"}, old=True)
            self.assertEqual(reply.status, 422, f"la v1 no declara {key}")
        self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.old[P104],)), "published")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[P104],)), 9)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.new[P104],)), 7)
        listed = await call("GET", f"/api/captures?form_code={P104}&machine_code=MP1", cookie=await self.cookie("OPERACION"))
        self.assertIn(capture["id"], [c["id"] for c in listed.json()])
        new, _ = await self.post(assignment, P104, v104())
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 2, "las capturas nuevas usan la versión 2")

    async def test_other_production_forms_are_not_affected_by_the_dependency_hook(self):
        assignment = await self.assignment("MP1")
        reply, _ = await self.post(assignment, "VINTO-P1-02", {k: v for k, v in _fill(FORMS["VINTO-P1-02"]["fields"]).items()})
        self.assertEqual(reply.status, 201, reply.text)


def _fill(fields):
    out = {}
    for n, f in enumerate(fields):
        if f["source"] != "manual" or f["key"] in ("observaciones", "observacion"):
            continue
        out[f["key"]] = f"{n}.25" if f["value_type"] == "decimal" else ("06:30" if f["value_type"] == "time" else "dato ficticio MF-12B")
    return out


class P116Tests(Base):
    async def test_a_weighing_is_one_capture_for_every_type_and_origin(self):
        assignment = await self.assignment("GAMBINI")
        n = 0
        for tipo in TIPOS:
            for origen in ORIGENES:
                reply, _ = await self.post(assignment, P116, v116(tipo_merma=tipo, origen_merma=origen, numero_correlativo=f"M-{n + 1:04d}"))
                self.assertEqual(reply.status, 201, (tipo, origen, reply.text))
                capture = reply.json()["capture"]
                self.assertEqual(capture["form"]["version_number"], 3)
                self.assertEqual((capture["values"]["tipo_merma"], capture["values"]["origen_merma"], capture["values"]["peso_merma_kg"]), (tipo, origen, "12.5"))
                stored = self.stored(capture["id"])
                self.assertEqual((stored["tipo_merma"], stored["origen_merma"]), (("text", tipo), ("text", origen)), "texto literal")
                self.assertEqual(stored["peso_merma_kg"], ("decimal", "12.5"))
                n += 1
        self.assertEqual(self.count(assignment), 18, "una pesada por captura")

    async def test_required_fields_closed_lists_and_decimal_weight(self):
        assignment = await self.assignment("OMET_I")
        good = v116()
        for key in ("hora_inicio", "hora_fin", "numero_correlativo", "tipo_merma", "origen_merma", "peso_merma_kg"):
            reply, _ = await self.post(assignment, P116, without(good, key))
            self.assertEqual(reply.status, 422, key)
            self.assertIn(key, reply.text)
        self.assertEqual((await self.post(assignment, P116, without(good, "observacion")))[0].status, 201, "la observación es opcional")
        self.assertEqual((await self.post(assignment, P116, v116(observacion="rollo roto")))[0].status, 201)
        for key, bad in (("tipo_merma", "Otro"), ("tipo_merma", "hoja doble"), ("tipo_merma", "Hoja Doble"), ("origen_merma", "Otro"), ("origen_merma", "logs"), ("origen_merma", "MAQUINA")):
            reply, _ = await self.post(assignment, P116, v116(**{key: bad}))
            self.assertEqual(reply.status, 422, (key, bad))
        for bad in ("abc", "1e3", "12 kg", "", None, True):
            self.assertEqual((await self.post(assignment, P116, v116(peso_merma_kg=bad)))[0].status, 422, f"peso {bad!r}")
        for ok in ("0", "0.25", "1234.5", 7):
            self.assertEqual((await self.post(assignment, P116, v116(peso_merma_kg=ok)))[0].status, 201, f"peso {ok!r}")
        for key in (*SIX, "total_merma_kg"):
            reply, _ = await self.post(assignment, P116, {**good, key: "1"})
            self.assertEqual(reply.status, 422, key)
            self.assertIn("campo desconocido", reply.text)

    async def test_general_hours_of_mf11_are_kept(self):
        assignment = await self.assignment("SINCRO_II")
        n = self.count(assignment)
        for bad in ("24:00", "12:60", "7:30", "abc", "", None):
            for key in ("hora_inicio", "hora_fin"):
                self.assertEqual((await self.post(assignment, P116, v116(**{key: bad})))[0].status, 422, (key, bad))
        for start, end in (("00:00", "23:59"), ("23:30", "00:15"), ("10:00", "09:00"), ("08:00", "08:00")):
            reply, _ = await self.post(assignment, P116, v116(hora_inicio=start, hora_fin=end, numero_correlativo=f"H-{start}"))
            self.assertEqual(reply.status, 201, (start, end))
            capture = reply.json()["capture"]
            self.assertEqual((capture["values"]["hora_inicio"], capture["values"]["hora_fin"]), (f"{start}:00", f"{end}:00"), "tal como se digitó: sin UTC, sin duración, sin orden")
            self.assertEqual(self.stored(capture["id"])["hora_inicio"], ("time", f"{start}:00"))
            self.assertEqual(capture["operating_date"], "2026-10-06", "la fecha operativa no se deduce de las horas")
        self.assertEqual(self.count(assignment), n + 4)

    async def test_the_correlative_stays_manual_and_no_uniqueness_is_imposed(self):
        assignment = await self.assignment("GAMBINI")
        first, _ = await self.post(assignment, P116, v116(numero_correlativo="REPETIDO-1"))
        second, _ = await self.post(assignment, P116, v116(numero_correlativo="REPETIDO-1", tipo_merma="Cartón"))
        self.assertEqual((first.status, second.status), (201, 201), "sin ámbito de unicidad aprobado, el correlativo se guarda tal como se digita")
        self.assertEqual(self.stored(first.json()["capture"]["id"])["numero_correlativo"], ("text", "REPETIDO-1"))
        self.assertEqual(self.stored(second.json()["capture"]["id"])["numero_correlativo"], ("text", "REPETIDO-1"))
        reply, _ = await self.post(assignment, P116, v116(numero_correlativo=""))
        self.assertEqual(reply.status, 422, "pero sí es obligatorio")
        reply, _ = await self.post(assignment, P116, v116(numero_correlativo="   "))
        self.assertEqual(reply.status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s AND (key LIKE '%%correlativo%%') AND source <> 'manual'", (self.new[P116],)), 0, "no hay numeración automática")

    async def test_old_versions_stay_readable_and_are_not_converted_into_weighings(self):
        assignment = await self.assignment("GAMBINI")
        v2 = {"hora_inicio": "06:30", "hora_fin": "14:45", "numero_correlativo": "C-2", **{k: str(n + 1) for n, k in enumerate(SIX)}}
        old, _ = await self.post(assignment, P116, v2, old=True)
        self.assertEqual(old.status, 201, old.text)
        capture = old.json()["capture"]
        self.assertEqual(capture["form"]["version_number"], 2)
        self.assertEqual({k: capture["values"][k] for k in SIX}, {k: str(n + 1) for n, k in enumerate(SIX)}, "las seis cantidades originales, intactas")
        for key in ("tipo_merma", "origen_merma", "peso_merma_kg"):
            self.assertNotIn(key, capture["values"], "no se inventa una pesada")
        got = await self.get(capture["id"])
        self.assertEqual((got.status, got.json()["values"]), (200, capture["values"]))
        for key in ("tipo_merma", "origen_merma", "peso_merma_kg"):
            reply, _ = await self.post(assignment, P116, {**v2, key: "Hoja doble"}, old=True)
            self.assertEqual(reply.status, 422, f"la v2 no declara {key}")
        self.assertEqual(self.scalar("SELECT status FROM vinto_config.form_version WHERE id = %s", (self.old[P116],)), "published")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.old[P116],)), 10)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_config.field_definition WHERE form_version_id = %s", (self.new[P116],)), 7)
        v1_values = {"numero_correlativo": "C-1", **{k: "1" for k in SIX}, "observacion": "viejo"}
        v1, _ = await self.post(assignment, P116, v1_values, old=True)  # v1 se reproduce con la definición v2 sin horas: no es obligatorio verificarla aquí; las horas sí lo son en v2
        self.assertEqual(v1.status, 422, "las horas ya eran obligatorias en la v2")
        listed = await call("GET", f"/api/captures?form_code={P116}&machine_code=GAMBINI", cookie=await self.cookie("OPERACION"))
        self.assertIn(capture["id"], [c["id"] for c in listed.json()])
        new, _ = await self.post(assignment, P116, v116())
        self.assertEqual(new.json()["capture"]["form"]["version_number"], 3)

    async def test_p1_16_is_available_in_all_its_machines_and_idempotent(self):
        for machine in FORMS[P116]["machines"]:
            assignment = await self.assignment(machine)
            reply, body = await self.post(assignment, P116, v116())
            self.assertEqual(reply.status, 201, (machine, reply.text))
            again = await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))
            self.assertEqual((again.status, again.json()["capture"]["id"]), (200, reply.json()["capture"]["id"]))
            self.assertEqual(self.count(assignment), 1)

    async def test_authorization_is_unchanged(self):
        assignment = await self.assignment("GAMBINI")
        reply, _ = await self.post(assignment, P116, v116(), who="CALIDAD")
        self.assertEqual(reply.status, 403)
        reply, _ = await self.post(assignment, P116, v116(), who="SIN_SECTOR")
        self.assertIn(reply.status, (403, 404))
        self.assertEqual(self.count(assignment), 0)


class ProductionImportScenarioTests(unittest.TestCase):
    """Producción tiene P1-04 v1 y P1-16 v2 (y MF-05 a MF-12A ya importados): el importador debe AÑADIR las dos versiones nuevas y dejar todo lo anterior exactamente igual."""

    @classmethod
    def setUpClass(cls):
        cls.database = f"vinto_mf12b_imp_{uuid4().hex[:10]}_test"
        create_database(cls.database)
        cls.connection = connect(cls.database)
        with contextlib.redirect_stdout(io.StringIO()):
            apply_migrations(cls.connection, read_migrations())
        reference.apply(cls.connection, variant("1" * 64, NEW_VERSION))

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
        links = c.execute(f"""SELECT f.code, v.version_number, m.code FROM vinto_config.form_version_machine l JOIN vinto_config.form_version v ON v.id = l.form_version_id
                              JOIN vinto_config.form f ON f.id = v.form_id JOIN vinto_master.machine m ON m.id = l.machine_id WHERE {where} ORDER BY 1, 2, 3""").fetchall()
        options = c.execute(f"""SELECT f.code, v.version_number, o.option_key, o.label, o.display_order FROM vinto_config.field_option o JOIN vinto_config.form_version v ON v.id = o.form_version_id
                                JOIN vinto_config.form f ON f.id = v.form_id WHERE {where} ORDER BY 1, 2, 5""").fetchall()
        return versions, fields, links, options

    def test_the_bundle_adds_only_the_two_new_versions_and_is_idempotent(self):
        codes = ", ".join(f"'{c}'" for c in NEW_VERSION)
        old_where = " OR ".join(f"(f.code = '{c}' AND v.version_number = {NEW_VERSION[c] - 1})" for c in NEW_VERSION)
        other_where = f"f.code NOT IN ({codes})"
        old, other = self.snapshot(old_where), self.snapshot(other_where)
        self.assertEqual(len(old[0]), 2)
        dry = reference.dry_run(self.connection, BUNDLE)
        self.assertEqual(dry.conflicts, [])
        self.assertEqual(dry.counts["form_version"]["create"], 2)
        self.assertEqual(dry.counts["field"]["create"], 7 + 7)
        self.assertEqual(dry.counts["form_version_machine"]["create"], 2 + 11)
        self.assertEqual(dry.counts["field_group"]["create"], 0)
        self.assertEqual(dry.counts["option"]["create"], (3 + 6 + 2) + (6 + 3))
        self.assertEqual(self.snapshot(old_where), old, "el dry-run no escribe")
        result = reference.apply(self.connection, BUNDLE)
        self.assertEqual((result.mode, result.conflicts), ("applied", []))
        self.assertEqual(self.snapshot(old_where), old, "las versiones anteriores, sus campos, vínculos y opciones quedan idénticos")
        self.assertEqual(self.snapshot(other_where), other, "los demás formularios no se tocan")
        for code, number in NEW_VERSION.items():
            rows = self.connection.execute("SELECT v.version_number, v.status FROM vinto_config.form_version v JOIN vinto_config.form f ON f.id = v.form_id WHERE f.code = %s ORDER BY 1", (code,)).fetchall()
            self.assertEqual([r for r in rows if r[0] >= number - 1], [(number - 1, "published"), (number, "published")], code)
        again = reference.apply(self.connection, dataclasses.replace(BUNDLE, source_checksum="3" * 64))
        self.assertTrue(all(n["create"] == 0 for n in again.counts.values()), "segunda importación idempotente: no crea duplicados")


if __name__ == "__main__":
    unittest.main()
