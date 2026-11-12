"""CV-P112-01: P1-12 v4 desde OT a pallet (PostgreSQL17 efimero)."""
import asyncio
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

try:
    from test_assignments_api import call
except ModuleNotFoundError:
    from tests.test_assignments_api import call

DAY = datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)
ARTICLE = "10351"  # INInventario.Peso=1.74, PERLITA ECO PLUS 4*12
FORM = "VINTO-P1-12"
STATE = {}
BUNDLE = load_bundle()


def setUpModule():
    STATE["template"] = build_reference_template("vinto_cv_p112_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class PalletTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_cv_p112")
        cls.connection = connect(cls.database)
        cls.db_patch = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.db_patch.start()
        cls.users, cls.cookies = {}, {}
        cls.actor = create_user(cls.connection, username="cvp112.admin", display_name="QA Admin", profile_code="DATA_BALTREK", password="cvp112-" + secrets.token_urlsafe(18), sectors=()).user_id
        for profile in ("JEFATURA", "SUPERVISION", "OPERACION"):
            password = "cvp112-" + secrets.token_urlsafe(18)
            created = create_user(cls.connection, username="cvp112." + profile.lower(),
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
        for target in (capture_service, assignments_service):
            mocked = patch.object(target, "_now", return_value=DAY)
            mocked.start()
            self.addCleanup(mocked.stop)

    async def cookie(self, profile):
        if profile not in self.cookies:
            created, password = self.users[profile]
            reply = await call("POST", "/api/auth/login",
                               json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, reply.text)
            self.cookies[profile] = reply.set_cookie_value()
        return self.cookies[profile]

    async def assignment(self, article_code=ARTICLE):
        reply = await call("POST", "/api/work-orders", cookie=await self.cookie("JEFATURA"),
                           json_body={"machine_code": "GAMBINI", "lines": [
                               {"pv_reference": "PV-P112", "article_code": article_code,
                                "quantity": 10, "due_date": "2026-11-01"}]})
        self.assertEqual(reply.status, 201, reply.text)
        published = await call("POST", f"/api/work-orders/{reply.json()['id']}/publish",
                               cookie=await self.cookie("JEFATURA"))
        self.assertEqual(published.status, 200, published.text)
        data = published.json()
        assigned = await call("POST", "/api/assignments/activate",
                              cookie=await self.cookie("SUPERVISION"),
                              json_body={"work_order_id": data["id"],
                                         "baseline_line_id": data["baseline"]["lines"][0]["id"]})
        self.assertEqual(assigned.status, 201, assigned.text)
        return data, assigned.json()["assignment"]

    def payload(self, assignment, **overrides):
        body = {"capture_id": str(uuid4()), "form_code": FORM, "assignment_id": assignment["id"],
                "device_key": str(uuid4()),
                "values": {"cantidad_jabas": 2, "hora_inicio": "08:15", "hora_fin": "09:05"}}
        body.update(overrides)
        return body

    async def post(self, body):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie("OPERACION"))

    def count(self, table):
        return self.connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

    async def test_vinto_app_pallet_table_acl_is_least_privilege(self):
        # The dedicated CI workflow provisions vinto_app BEFORE migrations.
        # Other isolated suites without cluster roles may skip this focused ACL check.
        role_present = self.connection.execute(
            "SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'vinto_app')"
        ).fetchone()[0]
        if not role_present:
            self.skipTest("Dedicated CV-P112 workflow provisions vinto_app for ACL coverage")

        expected = {
            "vinto_master.pallet_nominal_weight": {"SELECT"},
            "vinto_txn.production_pallet": {"SELECT", "INSERT"},
        }
        for table, allowed in expected.items():
            for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE", "TRUNCATE",
                              "REFERENCES", "TRIGGER"):
                with self.subTest(table=table, privilege=privilege):
                    permitted = self.connection.execute(
                        "SELECT has_table_privilege('vinto_app', %s, %s)",
                        (table, privilege),
                    ).fetchone()[0]
                    self.assertEqual(permitted, privilege in allowed)

    async def test_source_and_v4_schema(self):
        form = next(f for f in BUNDLE.forms if f["code"] == FORM)
        self.assertEqual(form["version_number"], 4)
        self.assertEqual({f["key"] for f in form["fields"]},
                         {"cantidad_jabas", "hora_inicio", "hora_fin"})
        self.assertTrue(all(f["required"] for f in form["fields"]))
        self.assertEqual(self.connection.execute(
            "SELECT nominal_weight_kg FROM vinto_master.pallet_nominal_weight WHERE article_code=%s AND revision=1",
            (ARTICLE,)).fetchone()[0], Decimal("1.74"))
        self.assertEqual(self.count("vinto_master.pallet_nominal_weight"), 73)  # 52 originales P1-12 + 21 aditivos P1-13

    async def test_authorized_weight_preview_is_bound_to_ot_and_line(self):
        order, assignment = await self.assignment()
        url = f"/api/production/pallet-preview?assignment_id={assignment['id']}"
        cookie = await self.cookie("OPERACION")
        # Permisos efectivos, no solo el modo observe: sin grant no hay vista previa.
        without_grant = await call("GET", url, cookie=cookie)
        self.assertEqual(without_grant.status, 404)
        user_id = self.users["OPERACION"][0].user_id
        self.assertTrue(grant_machine_form(self.connection, user_id=user_id,
            machine_code="GAMBINI", form_code=FORM, actor_id=self.actor))
        ok = await call("GET", url, cookie=cookie)
        self.assertEqual(ok.status, 200, ok.text)
        info = ok.json()
        self.assertEqual(info["article_code"], ARTICLE)
        self.assertEqual(info["line_code"], "L1")
        self.assertEqual(info["work_order"], order["number"])
        self.assertEqual(Decimal(info["nominal_weight_kg"]), Decimal("1.74"))
        self.assertEqual(info["unit"], "kg/jaba")
        self.assertTrue(info["weight_available"])
        unknown = await call("GET", f"/api/production/pallet-preview?assignment_id={uuid4()}",
                             cookie=await self.cookie("OPERACION"))
        self.assertEqual(unknown.status, 404)
        anonymous = await call("GET", url)
        self.assertEqual(anonymous.status, 401)
        self.assertTrue(revoke_machine_form(self.connection, user_id=user_id, machine_code="GAMBINI", form_code=FORM, actor_id=self.actor))
        after_revoke = await call("GET", url, cookie=cookie)
        self.assertEqual(after_revoke.status, 404)

    async def test_first_pallet_and_atomic_snapshot(self):
        order, assignment = await self.assignment()
        body = self.payload(assignment)
        reply = await self.post(body)
        self.assertEqual(reply.status, 201, reply.text)
        p = reply.json()["capture"]["pallet"]
        self.assertEqual((p["number"], p["quantity_jabas"]), (1, 2))
        self.assertEqual(Decimal(p["nominal_weight_kg"]), Decimal("1.74"))
        self.assertEqual(Decimal(p["total_weight_kg"]), Decimal("3.48"))
        stored = self.connection.execute(
            """SELECT pallet_number, quantity_jabas, nominal_weight_kg, total_weight_kg,
                      work_order_id, line_code, weight_source_sha256
               FROM vinto_txn.production_pallet WHERE capture_id=%s""", (body["capture_id"],)).fetchone()
        self.assertEqual(stored[:4], (1, 2, Decimal("1.740000"), Decimal("3.480000")))
        self.assertEqual(stored[4], order["id"] if isinstance(order["id"], type(stored[4])) else __import__("uuid").UUID(order["id"]))
        self.assertEqual(stored[5], "L1")
        self.assertEqual(len(stored[6]), 64)
        read = await call("GET", f"/api/captures/{body['capture_id']}", cookie=await self.cookie("OPERACION"))
        self.assertEqual(read.status, 200, read.text)
        self.assertEqual(read.json()["pallet"], p)

    async def test_retry_is_idempotent_and_does_not_consume_number(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        first = await self.post(body)
        self.assertEqual(first.status, 201, first.text)
        baseline = self.count("vinto_txn.production_pallet")
        again = await self.post(body)
        self.assertEqual(again.status, 200, again.text)
        self.assertTrue(again.json()["already_submitted"])
        self.assertEqual(again.json()["capture"]["pallet"], first.json()["capture"]["pallet"])
        self.assertEqual(self.count("vinto_txn.production_pallet"), baseline)
        different = {**body, "values": {**body["values"], "cantidad_jabas": 3}}
        conflict = await self.post(different)
        self.assertEqual(conflict.status, 409)

    async def test_positive_quantity_and_no_client_weight_or_number(self):
        _, assignment = await self.assignment()
        baseline = self.count("vinto_txn.production_pallet")
        for quantity in (0, -1, 1.5, "0"):
            reply = await self.post(self.payload(assignment, values={
                "cantidad_jabas": quantity, "hora_inicio": "08:15", "hora_fin": "09:05"}))
            self.assertEqual(reply.status, 422, (quantity, reply.text))
        for unexpected in ("numero_pallet", "peso_nominal_kg", "peso_total_kg"):
            reply = await self.post(self.payload(assignment, values={
                "cantidad_jabas": 2, "hora_inicio": "08:15", "hora_fin": "09:05",
                unexpected: "999999"}))
            self.assertEqual(reply.status, 422, (unexpected, reply.text))
        self.assertEqual(self.count("vinto_txn.production_pallet"), baseline)

    async def test_two_simultaneous_captures_unique_and_new_ot_starts_at_one(self):
        _, a = await self.assignment()
        first, second = self.payload(a), self.payload(a)
        x, y = await asyncio.gather(self.post(first), self.post(second))
        self.assertEqual((x.status, y.status), (201, 201), (x.text, y.text))
        self.assertEqual(sorted([x.json()["capture"]["pallet"]["number"],
                                 y.json()["capture"]["pallet"]["number"]]), [1, 2])
        # La nueva OT es una clave de contador independiente.
        self.connection.execute(
            "UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s",
            (a["id"],))
        _, b = await self.assignment()
        third = await self.post(self.payload(b))
        self.assertEqual(third.status, 201, third.text)
        self.assertEqual(third.json()["capture"]["pallet"]["number"], 1)

    async def test_historical_p112_versions_are_not_backfilled(self):
        self.assertEqual(self.connection.execute(
            "SELECT COUNT(*) FROM vinto_txn.production_pallet WHERE pallet_number < 1").fetchone()[0], 0)
        rows = self.connection.execute(
            """SELECT fv.version_number, COUNT(f.id)
               FROM vinto_config.form_version fv JOIN vinto_config.form f ON f.id=fv.form_id
               WHERE f.code=%s GROUP BY fv.version_number""", (FORM,)).fetchall()
        self.assertIn((4, 1), rows)
