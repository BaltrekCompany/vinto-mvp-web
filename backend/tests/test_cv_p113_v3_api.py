"""CV-P113-01: P1-13 v3, receta completa y pallet por articulo/OT/linea en PG17 aislado."""
import secrets
import unittest
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr
from app import capture_service
from app.assignments import service as assignments_service
from app.auth.service import create_user
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.seed.bundle import load_bundle
from app.p111_recipe_policy import recipe_codes
try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
FORM = "VINTO-P1-13"
ARTICLE = "11203"
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_cv_p113_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class P113V3Tests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_cv_p113")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users = {}
        cls.cookies = {}
        cls.admin = create_user(
            cls.connection, username="cvp113.admin", display_name="QA Admin", profile_code="DATA_BALTREK",
            password="cvp113-" + secrets.token_urlsafe(18), sectors=()).user_id
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION"):
            password = "cvp113-" + secrets.token_urlsafe(18)
            u = create_user(cls.connection, username="cvp113." + profile.lower(), display_name="QA "+profile,
                            profile_code=profile, password=password, sectors=("CONVERSION",))
            cls.users[profile] = (u, password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute(
            "UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        for target in (capture_service, assignments_service):
            mock = patch.object(target, "_now", return_value=DAY)
            mock.start()
            self.addCleanup(mock.stop)

    async def cookie(self, profile):
        if profile not in self.cookies:
            user, password = self.users[profile]
            response = await call("POST", "/api/auth/login",
                                  json_body={"username": user.username, "password": password})
            self.assertEqual(response.status, 200, response.text)
            self.cookies[profile] = response.set_cookie_value()
        return self.cookies[profile]

    async def assignment(self, machine="OMET_II", article=ARTICLE):
        new = await call("POST", "/api/work-orders", cookie=await self.cookie("JEFATURA"),
                         json_body={"machine_code": machine, "lines": [
                             {"pv_reference": "PV-P113", "article_code": article,
                              "quantity": 10, "due_date": "2026-11-01"}]})
        self.assertEqual(new.status, 201, new.text)
        published = await call("POST", "/api/work-orders/" + new.json()["id"] + "/publish",
                               cookie=await self.cookie("JEFATURA"))
        self.assertEqual(published.status, 200, published.text)
        order = published.json()
        activated = await call("POST", "/api/assignments/activate",
                               cookie=await self.cookie("SUPERVISION"),
                               json_body={"work_order_id": order["id"],
                                          "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(activated.status, 201, activated.text)
        return order, activated.json()["assignment"]

    def payload(self, assignment, **extras):
        return {"capture_id": str(uuid4()), "form_code": FORM, "assignment_id": assignment["id"],
                "device_key": str(uuid4()), "values": {
                    "tipo_bobina": "BC-1229-210", "numero_bobina": "BOB-P113-1",
                    "saldo_inicial_kg": "15", "ingreso_kg": "20", "saldo_final_kg": "5",
                    "cantidad_jabas": 10, "hora_inicio": "08:15", "hora_fin": "09:05"}, **extras}

    async def send(self, data):
        return await call("POST", "/api/captures", cookie=await self.cookie("OPERACION"), json_body=data)

    async def test_reference_recipe_and_weight_source(self):
        bundle = load_bundle()
        form = next(f for f in bundle.forms if f["code"] == FORM)
        self.assertEqual(form["version_number"], 4)
        self.assertEqual({f["key"] for f in form["fields"]}, {
            "tipo_bobina", "numero_bobina", "saldo_inicial_kg", "ingreso_kg", "saldo_final_kg",
            "cantidad_jabas", "hora_inicio", "hora_fin", "observaciones"})
        self.assertEqual({f["key"] for f in form["fields"] if f["required"]},
                         {"tipo_bobina", "numero_bobina"})
        self.assertEqual(recipe_codes()["11203"], frozenset({"BC-1229-210", "9570", "9632"}))
        self.assertNotIn("11104", recipe_codes())
        self.assertNotIn("11202", recipe_codes())
        w = self.connection.execute(
            "SELECT nominal_weight_kg, source_unit, source_sha256 FROM vinto_master.pallet_nominal_weight WHERE article_code=%s",
            ("11203",)).fetchone()
        self.assertEqual((w[0], w[1]), (Decimal("2.02"), "PACK"))
        self.assertEqual(w[2], "9d692492df2af74d0abf084de9ac7c67848abb58fea93a2ee500f8b049cf8228")
        self.assertIsNone(self.connection.execute(
            "SELECT nominal_weight_kg FROM vinto_master.pallet_nominal_weight WHERE article_code='11503'"
        ).fetchone())
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_master.pallet_nominal_weight").fetchone()[0], 73)

    async def test_preview_bound_to_omet_and_authorization(self):
        _, a = await self.assignment()
        url = "/api/production/pallet-preview?assignment_id=" + str(a["id"])
        unauth = await call("GET", url, cookie=await self.cookie("OPERACION"))
        self.assertEqual(unauth.status, 404, unauth.text)
        self.assertTrue(grant_machine_form(
            self.connection, user_id=self.users["OPERACION"][0].user_id,
            machine_code="OMET_II", form_code=FORM, actor_id=self.admin))
        allowed = await call("GET", url, cookie=await self.cookie("OPERACION"))
        self.assertEqual(allowed.status, 200, allowed.text)
        self.assertEqual(allowed.json()["article_code"], "11203")
        self.assertEqual(Decimal(allowed.json()["nominal_weight_kg"]), Decimal("2.02"))
        self.assertTrue(revoke_machine_form(
            self.connection, user_id=self.users["OPERACION"][0].user_id,
            machine_code="OMET_II", form_code=FORM, actor_id=self.admin))
        again = await call("GET", url, cookie=await self.cookie("OPERACION"))
        self.assertEqual(again.status, 404)

    async def test_pallet_persisted_and_idempotent_without_inventory_movement(self):
        order, a = await self.assignment()
        body = self.payload(a)
        created = await self.send(body)
        self.assertEqual(created.status, 201, created.text)
        record = created.json()["capture"]
        self.assertEqual(record["form"]["version_number"], 4)
        self.assertEqual(record["values"]["tipo_bobina"], "BC-1229-210")
        self.assertNotIn("consumo", record["values"])
        self.assertNotIn("peso_total_pallet", record["values"])
        pallet = record["pallet"]
        self.assertEqual((pallet["number"], pallet["quantity_jabas"]), (1, 10))
        self.assertEqual(Decimal(pallet["nominal_weight_kg"]), Decimal("2.02"))
        self.assertEqual(Decimal(pallet["total_weight_kg"]), Decimal("20.20"))
        same = await self.send(body)
        self.assertEqual(same.status, 200, same.text)
        self.assertTrue(same.json()["already_submitted"])
        self.assertEqual(same.json()["capture"]["pallet"], pallet)
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_txn.production_pallet WHERE work_order_id=%s",
            (order["id"],)).fetchone()[0], 1)
        second = await self.send(self.payload(a))
        self.assertEqual(second.status, 201, second.text)
        self.assertEqual(second.json()["capture"]["pallet"]["number"], 2)

    async def test_accepts_all_three_materials_but_rejects_outside_recipe(self):
        _, a = await self.assignment()
        for material in ("BC-1229-210", "9570", "9632"):
            body = self.payload(a)
            body["values"]["tipo_bobina"] = material
            self.assertEqual((await self.send(body)).status, 201, material)
        for material in ("M3-3038", "11103", "no-existe"):
            body = self.payload(a)
            body["values"]["tipo_bobina"] = material
            bad = await self.send(body)
            self.assertEqual(bad.status, 422, bad.text)
        invalid = self.payload(a)
        invalid["values"]["cantidad_jabas"] = 0
        self.assertEqual((await self.send(invalid)).status, 422)

    async def test_missing_recipe_and_unvalidated_unit_block_without_writes(self):
        _, without_recipe = await self.assignment(machine="8_2", article="11104")
        bad = self.payload(without_recipe)
        bad["values"]["tipo_bobina"] = "9126"
        self.assertEqual((await self.send(bad)).status, 422)
        _, missing_weight = await self.assignment(machine="PANUELERA", article="11503")
        body = self.payload(missing_weight)
        body["values"]["tipo_bobina"] = "BC-3451-420"
        self.assertEqual((await self.send(body)).status, 422)
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_txn.production_pallet WHERE article_version_id IN "
            "(SELECT id FROM vinto_master.article_version WHERE article_id IN "
            "(SELECT id FROM vinto_master.article WHERE code IN ('11104','11503')))").fetchone()[0], 0)


    async def test_all_eight_conversion_machines_create_pallets(self):
        """Prueba funcional real por las ocho maquinas aprobadas de P1-13.
        Articulo/material son parejas vigentes de article_machines y receta homologada.
        Una captura valida registra un pallet con el peso correspondiente al PRODUCTO,
        no al material. Ningun caso modifica inventario.
        """
        from app.production_pallets import P113_MACHINES, form_for_machine

        samples = [
            ("OMET_I", "11103", "9126", "2.48"),
            ("OMET_II", "11203", "BC-1229-210", "2.02"),
            ("8_2", "11204", "BC-1458", "2.66"),
            ("8_5", "11205", "BC-1234-200", "2.89"),
            ("8002", "11110", "9120", "1.3962"),
            ("SERV_4", "11102", "9120", "1.33"),
            ("WALLY", "11307", "9123", "1.6"),
            ("PANUELERA", "11502", "9188", "6"),
        ]
        self.assertEqual({machine for machine, *_ in samples}, set(P113_MACHINES))
        form = next(f for f in load_bundle().forms if f["code"] == FORM)
        self.assertEqual(set(form["machines"]), set(P113_MACHINES))
        for machine, article, material, nominal in samples:
            with self.subTest(machine=machine, article=article):
                self.assertEqual(form_for_machine(machine), FORM)
                self.assertIn(material, recipe_codes()[article])
                available = self.connection.execute(
                    """SELECT 1 FROM vinto_master.article_machine am
                       JOIN vinto_master.article a ON a.id = am.article_id
                       JOIN vinto_master.machine m ON m.id = am.machine_id
                       WHERE a.code = %s AND m.code = %s""",
                    (article, machine),
                ).fetchone()
                self.assertIsNotNone(available, (machine, article))
                order, assignment = await self.assignment(machine=machine, article=article)
                request = self.payload(assignment)
                request["values"]["tipo_bobina"] = material
                result = await self.send(request)
                self.assertEqual(result.status, 201, (machine, result.text))
                capture = result.json()["capture"]
                self.assertEqual(capture["machine"]["code"], machine)
                self.assertEqual(capture["line"]["article"]["code"], article)
                pallet = capture["pallet"]
                self.assertEqual(pallet["number"], 1)
                self.assertEqual(pallet["quantity_jabas"], 10)
                self.assertEqual(Decimal(pallet["nominal_weight_kg"]), Decimal(nominal))
                self.assertEqual(Decimal(pallet["total_weight_kg"]), 10 * Decimal(nominal))
                self.assertEqual(self.connection.execute(
                    "SELECT count(*) FROM vinto_txn.production_pallet WHERE work_order_id=%s",
                    (order["id"],),
                ).fetchone()[0], 1)

    async def test_v4_only_two_required_and_no_pallet_or_counter(self):
        """Con solo material y numero guarda captura, sin pallet ficticio."""
        order, assignment = await self.assignment()
        body = self.payload(assignment)
        body["values"] = {"tipo_bobina": "9570", "numero_bobina": "QA-V4-ONLY-TWO"}
        first = await self.send(body)
        self.assertEqual(first.status, 201, first.text)
        created = first.json()["capture"]
        self.assertEqual(created["form"]["version_number"], 4)
        self.assertEqual(created["values"], body["values"])
        self.assertIsNone(created["pallet"])
        self.assertEqual(self.connection.execute(
            "SELECT count(*) FROM vinto_txn.production_pallet WHERE work_order_id = %s",
            (order["id"],)).fetchone()[0], 0)
        # Reintento idempotente tampoco debe consumir correlativo.
        second = await self.send(body)
        self.assertEqual(second.status, 200, second.text)
        self.assertTrue(second.json()["already_submitted"])
        self.assertIsNone(second.json()["capture"]["pallet"])
        read = await call("GET", f"/api/captures/{body['capture_id']}",
                          cookie=await self.cookie("OPERACION"))
        self.assertEqual(read.status, 200, read.text)
        self.assertIsNone(read.json()["pallet"])
        # Solo jabas + campos obligatorios: aun sin horas/saldos se crea pallet N.1.
        with_jabas = self.payload(assignment)
        with_jabas["values"] = {
            "tipo_bobina": "9632", "numero_bobina": "QA-V4-WITH-PALLET",
            "cantidad_jabas": 10,
        }
        pallet_reply = await self.send(with_jabas)
        self.assertEqual(pallet_reply.status, 201, pallet_reply.text)
        snapshot = pallet_reply.json()["capture"]["pallet"]
        self.assertEqual((snapshot["number"], snapshot["quantity_jabas"]), (1, 10))
        self.assertEqual(Decimal(snapshot["nominal_weight_kg"]), Decimal("2.02"))
        self.assertEqual(Decimal(snapshot["total_weight_kg"]), Decimal("20.20"))
        self.assertNotIn("hora_inicio", pallet_reply.json()["capture"]["values"])
        self.assertNotIn("saldo_final_kg", pallet_reply.json()["capture"]["values"])

    async def test_v4_partial_optional_saldos_hours_and_missing_weight_without_pallet(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        body["values"] = {
            "tipo_bobina": "BC-1229-210", "numero_bobina": "QA-PARTIAL",
            "saldo_inicial_kg": "15.5", "hora_inicio": "08:15",
        }
        response = await self.send(body)
        self.assertEqual(response.status, 201, response.text)
        values = response.json()["capture"]["values"]
        self.assertEqual(Decimal(values["saldo_inicial_kg"]), Decimal("15.5"))
        self.assertNotIn("ingreso_kg", values)
        self.assertNotIn("saldo_final_kg", values)
        self.assertNotIn("hora_fin", values)
        self.assertIsNone(response.json()["capture"]["pallet"])
        # La unidad de inventario UN de 11503 bloquea PALLET, no captura sin jabas.
        _, no_weight = await self.assignment(machine="PANUELERA", article="11503")
        payload = self.payload(no_weight)
        payload["values"] = {
            "tipo_bobina": "BC-3451-420", "numero_bobina": "QA-NO-WEIGHT",
        }
        without_pallet = await self.send(payload)
        self.assertEqual(without_pallet.status, 201, without_pallet.text)
        self.assertIsNone(without_pallet.json()["capture"]["pallet"])

    async def test_v4_invalid_optional_input_rejected_without_partial_writes(self):
        _, assignment = await self.assignment()
        for key, bad in (
            ("cantidad_jabas", 0), ("cantidad_jabas", -1), ("cantidad_jabas", "1.5"),
            ("saldo_inicial_kg", "abc"), ("ingreso_kg", "xyz"),
            ("saldo_final_kg", "1,2,3"), ("hora_inicio", "25:00"),
            ("hora_fin", "09:89"),
        ):
            with self.subTest(key=key, bad=bad):
                payload = self.payload(assignment)
                payload["values"] = {
                    "tipo_bobina": "9570", "numero_bobina": "QA-INVALID",
                    key: bad,
                }
                response = await self.send(payload)
                self.assertEqual(response.status, 422, response.text)
        for mandatory in ("tipo_bobina", "numero_bobina"):
            payload = self.payload(assignment)
            payload["values"] = {
                "tipo_bobina": "9570", "numero_bobina": "QA-MISSING",
            }
            del payload["values"][mandatory]
            self.assertEqual((await self.send(payload)).status, 422)
