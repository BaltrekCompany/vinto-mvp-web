"""CV-P111 V4: saldos opcionales en P1-11 con PostgreSQL17 real y API central aislada."""
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr
from app import capture_service
from app.assignments import service as assignments_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.p111_recipe_policy import recipe_codes
from app.seed.bundle import load_bundle

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
FORM = "VINTO-P1-11"
PRODUCT = "10327"
CATALOG = recipe_codes()
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_cv_p111_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class RecipeConsumptionTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_cv_p111")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.cookies = {}
        cls.admin = create_user(cls.connection, username="cvp111.admin", display_name="QA Admin",
                                profile_code="DATA_BALTREK", password="cvp111-" + secrets.token_urlsafe(18),
                                sectors=()).user_id
        cls.users = {}
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION"):
            password = "cvp111-" + secrets.token_urlsafe(18)
            created = create_user(cls.connection, username="cvp111." + profile.lower(),
                                  display_name="QA " + profile, profile_code=profile,
                                  password=password, sectors=("CONVERSION",))
            cls.users[profile] = (created, password)

    @classmethod
    def tearDownClass(cls):
        cls.db_patch.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute(
            "UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'"
        )
        for module in (capture_service, assignments_service):
            mock = patch.object(module, "_now", return_value=DAY)
            mock.start()
            self.addCleanup(mock.stop)

    async def cookie(self, role):
        if role not in self.cookies:
            user, password = self.users[role]
            response = await call("POST", "/api/auth/login",
                                  json_body={"username": user.username, "password": password})
            self.assertEqual(response.status, 200, response.text)
            self.cookies[role] = response.set_cookie_value()
        return self.cookies[role]

    async def assignment(self, article=PRODUCT, machine="SINCRO_II"):
        response = await call("POST", "/api/work-orders", cookie=await self.cookie("JEFATURA"),
                              json_body={"machine_code": machine, "lines": [{
                                  "pv_reference": "PV-P111", "article_code": article,
                                  "quantity": 10, "due_date": "2026-11-01"}]})
        self.assertEqual(response.status, 201, response.text)
        published = await call("POST", f"/api/work-orders/{response.json()['id']}/publish",
                               cookie=await self.cookie("JEFATURA"))
        self.assertEqual(published.status, 200, published.text)
        document = published.json()
        activated = await call("POST", "/api/assignments/activate",
                               cookie=await self.cookie("SUPERVISION"),
                               json_body={"work_order_id": document["id"],
                                          "baseline_line_id": document["baseline"]["lines"][0]["id"]})
        self.assertEqual(activated.status, 201, activated.text)
        return activated.json()["assignment"]

    @staticmethod
    def row(**overrides):
        value = {
            "posicion": "no_aplica",
            "tipo_material": "9483",
            "numero_bobina": "M3-001",
            "saldo_inicial_kg": "100.5",
            "ingreso_kg": "20",
            "saldo_final_kg": "60.25",
        }
        value.update(overrides)
        return value

    def payload(self, assignment, rows=None):
        return {"capture_id": str(uuid4()), "form_code": FORM,
                "assignment_id": assignment["id"], "device_key": str(uuid4()),
                "values": {"_groups": {"bobinas": rows if rows is not None else [self.row()]}}}

    async def post(self, body):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))

    async def test_reference_is_real_v4_three_rows_and_optional_balances(self):
        definition = next(form for form in load_bundle().forms if form["code"] == FORM)
        self.assertEqual(definition["version_number"], 4)
        self.assertEqual(definition["groups"][0]["max_rows"], 3)
        self.assertEqual([o["option_key"] for o in definition["groups"][0]["fields"][0]["options"]],
                         ["superior", "inferior", "no_aplica"])
        self.assertEqual([f["key"] for f in definition["groups"][0]["fields"]],
                         ["posicion", "tipo_material", "numero_bobina",
                          "saldo_inicial_kg", "ingreso_kg", "saldo_final_kg"])
        self.assertEqual([f["required"] for f in definition["groups"][0]["fields"]],
                         [True, True, True, False, False, False])
        latest = self.connection.execute(
            """SELECT MAX(fv.version_number) FROM vinto_config.form f
               JOIN vinto_config.form_version fv ON fv.form_id=f.id
               WHERE f.code=%s AND fv.status='published'""", (FORM,)).fetchone()[0]
        self.assertEqual(latest, 4)
        self.assertEqual(len(CATALOG[PRODUCT]), 10)

    async def test_one_required_row_and_server_receipt_with_recipe(self):
        assignment = await self.assignment()
        request = self.payload(assignment)
        response = await self.post(request)
        self.assertEqual(response.status, 201, response.text)
        capture = response.json()["capture"]
        self.assertEqual(capture["form"]["version_number"], 4)
        self.assertEqual(capture["line"]["article"]["code"], PRODUCT)
        self.assertEqual(capture["values"]["_groups"]["bobinas"][0]["tipo_material"], "9483")
        self.assertEqual(len(capture["values"]["_groups"]["bobinas"]), 1)
        self.assertNotIn("consumo_kg", capture["values"])
        again = await self.post(request)
        self.assertEqual(again.status, 200, again.text)
        self.assertTrue(again.json()["already_submitted"])

    async def test_10327_is_approved_in_gambini_preserving_sincro_links(self):
        """Excepción operativa autorizada: 10327 es Conversión en el Excel;
        la máquina GAMBINI es una decisión explícita, no un campo del Excel."""
        permitted = self.connection.execute(
            """SELECT m.code FROM vinto_master.article_machine am
               JOIN vinto_master.article a ON a.id=am.article_id
               JOIN vinto_master.machine m ON m.id=am.machine_id
               WHERE a.code=%s ORDER BY m.code""", (PRODUCT,)).fetchall()
        self.assertEqual([r[0] for r in permitted], ["GAMBINI", "SINCRO_II", "SINCRO_III"])
        assignment = await self.assignment(machine="GAMBINI")
        result = await self.post(self.payload(assignment, [
            self.row(tipo_material="M3-3038", numero_bobina="M3-EN-GAMBINI")]))
        self.assertEqual(result.status, 201, result.text)
        capture = result.json()["capture"]
        self.assertEqual(capture["machine"]["code"], "GAMBINI")
        self.assertEqual(capture["line"]["article"]["code"], PRODUCT)
        self.assertEqual(capture["values"]["_groups"]["bobinas"][0]["tipo_material"], "M3-3038")

    async def test_three_rows_and_positions_persist_in_order(self):
        assignment = await self.assignment()
        body = self.payload(assignment, [
            self.row(),
            self.row(posicion="superior", tipo_material="9484", numero_bobina="M3-002"),
            self.row(posicion="inferior", tipo_material="M3-3038", numero_bobina="M3-003")])
        response = await self.post(body)
        self.assertEqual(response.status, 201, response.text)
        stored = response.json()["capture"]["values"]["_groups"]["bobinas"]
        self.assertEqual([row["numero_bobina"] for row in stored], ["M3-001", "M3-002", "M3-003"])

    async def test_three_positions_accept_missing_or_partial_balances_without_storing_zero(self):
        assignment = await self.assignment()
        rows = [
            {"posicion": "no_aplica", "tipo_material": "9483", "numero_bobina": "QA-EMPTY"},
            {"posicion": "superior", "tipo_material": "9484", "numero_bobina": "QA-ONE", "saldo_inicial_kg": "2"},
            {"posicion": "inferior", "tipo_material": "M3-3038", "numero_bobina": "QA-TWO",
             "saldo_inicial_kg": "2", "ingreso_kg": "3"},
        ]
        response = await self.post(self.payload(assignment, rows))
        self.assertEqual(response.status, 201, response.text)
        result = response.json()["capture"]
        self.assertEqual(result["form"]["version_number"], 4)
        self.assertEqual(result["values"]["_groups"]["bobinas"][0], rows[0])
        self.assertEqual(result["values"]["_groups"]["bobinas"][1]["saldo_inicial_kg"], "2")
        self.assertNotIn("saldo_final_kg", result["values"]["_groups"]["bobinas"][2])
        self.assertNotIn("consumo_kg", str(result["values"]))

    async def test_foreign_material_is_rejected_atomically(self):
        assignment = await self.assignment()
        alien = next(code for article, codes in CATALOG.items()
                     if article != PRODUCT for code in codes if code not in CATALOG[PRODUCT])
        first = self.payload(assignment, [self.row(tipo_material=alien)])
        response = await self.post(first)
        self.assertEqual(response.status, 422, response.text)
        self.assertIsNone(self.connection.execute(
            "SELECT id FROM vinto_txn.capture WHERE id=%s", (first["capture_id"],)).fetchone())
        missing = self.payload(assignment, [self.row(tipo_material="")])
        response = await self.post(missing)
        self.assertEqual(response.status, 422, response.text)

    async def test_invalid_optional_partial_and_fourth_row_fail(self):
        assignment = await self.assignment()
        cases = [
            [self.row(), {"tipo_material": "9483"}],
            [self.row(), self.row(), self.row(), self.row()],
            [],
            [self.row(posicion="inexistente")],
            [self.row(ingreso_kg="texto")],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                response = await self.post(self.payload(assignment, rows))
                self.assertEqual(response.status, 422, response.text)
