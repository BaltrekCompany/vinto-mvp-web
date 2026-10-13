"""M2-A HTTP contract of the multiform production engine: POST/GET /api/captures with a SYNTHETIC second form (ephemeral *_test database only).

The ASGI app is called directly with DATABASE_URL patched to an ephemeral database. The real policy (F6 only) is patched per test to enable the
synthetic code; the F6 contract is asserted again side by side. Nothing touches vinto.
"""

import asyncio
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app import capture_service as _capture_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from m2a_fixtures import SYNTHETIC_CODE, SYNTHETIC_QUALITY_CODE, SYNTHETIC_VALUES, install_production_form
    from test_assignments_api import PROFILES, call, order_body
except ModuleNotFoundError:
    from tests.m2a_fixtures import SYNTHETIC_CODE, SYNTHETIC_QUALITY_CODE, SYNTHETIC_VALUES, install_production_form
    from tests.test_assignments_api import PROFILES, call, order_body

STATE = {}
F6 = "VINTO-P1-06"
F6_VALUES = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}
ENABLED = frozenset({F6, SYNTHETIC_CODE})


def setUpModule():
    STATE["template"] = build_reference_template("vinto_m2aapi_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class MultiformApiCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_m2aapi")
        cls.connection = connect(cls.database)
        install_production_form(cls.connection)  # synthetic production form (MP1, MP3) in the ephemeral database only
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.users, cls.cookies = {}, {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (create_user(cls.connection, username=f"m2aapi.{profile.lower()}", display_name=profile.title(), profile_code=profile, password=password, sectors=("BOBINAS",)), password)
        password = "pw-" + secrets.token_urlsafe(18)  # an OPERACION user with NO sector grant
        cls.users["OPERACION_SIN_SECTOR"] = (create_user(cls.connection, username="m2aapi.sinsector", display_name="Sin sector", profile_code="OPERACION", password=password, sectors=()), password)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")
        policy = patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED)
        policy.start()
        self.addCleanup(policy.stop)

    async def cookie(self, profile):
        if profile not in self.cookies:
            created, password = self.users[profile]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, profile)
            self.cookies[profile] = reply.set_cookie_value()
        return self.cookies[profile]

    async def assignment(self, machine="MP1"):
        order = (await call("POST", "/api/work-orders", json_body=order_body(machine), cookie=await self.cookie("JEFATURA"))).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"),
                           json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(reply.status, 201)
        return order, reply.json()["assignment"]

    def payload(self, assignment, form_code=SYNTHETIC_CODE, **changes):
        body = {"capture_id": str(uuid4()), "form_code": form_code, "assignment_id": assignment["id"], "device_key": str(uuid4()),
                "values": dict(SYNTHETIC_VALUES if form_code == SYNTHETIC_CODE else F6_VALUES)}
        body.update(changes)
        return body

    async def post(self, body, profile="OPERACION"):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(profile))

    async def get(self, path, profile="OPERACION"):
        return await call("GET", path, cookie=await self.cookie(profile))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]


class WriteTests(MultiformApiCase):
    async def test_the_second_form_is_created_with_201_and_the_f6_response_shape(self):
        order, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment))
        self.assertEqual(reply.status, 201)
        data = reply.json()
        self.assertEqual((data["created"], data["already_submitted"]), (True, False))
        capture = data["capture"]
        self.assertEqual(set(capture), {"id", "status", "revision", "captured_at", "submitted_at", "form", "machine", "shift", "operating_date", "assignment", "work_order", "line", "values"})
        self.assertEqual((capture["form"]["code"], capture["form"]["version_number"], capture["status"], capture["revision"]), (SYNTHETIC_CODE, 1, "submitted", 1))
        self.assertEqual((capture["machine"]["code"], capture["assignment"]["id"], capture["work_order"]["id"]), ("MP1", assignment["id"], order["id"]))
        self.assertEqual(capture["values"], {"codigo_lote": "LOTE-001", "unidades": 12, "peso_kg": "34.250", "tipo": "alfa", "observaciones": "sintetico"})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (capture["id"],)), 1)

    async def test_f6_still_works_side_by_side_with_the_same_contract(self):
        _, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment, form_code=F6))
        self.assertEqual(reply.status, 201)
        capture = reply.json()["capture"]
        self.assertEqual((capture["form"]["code"], capture["values"]["peso_kg"], capture["status"]), (F6, "125.50", "submitted"))

    async def test_the_code_is_not_accepted_unless_it_is_enabled_even_if_published(self):
        _, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6})):
            before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
            reply = await self.post(self.payload(assignment))
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"))
            self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_idempotent_retry_200_and_conflict_409(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        self.assertEqual((await self.post(body)).status, 201)
        again = await self.post(body)
        self.assertEqual(again.status, 200)
        self.assertEqual((again.json()["created"], again.json()["already_submitted"]), (False, True))
        conflict = await self.post({**body, "values": {**body["values"], "unidades": 13}})
        self.assertEqual((conflict.status, conflict.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        cross = await self.post({**body, "form_code": F6, "values": dict(F6_VALUES)})
        self.assertEqual(cross.status, 409)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)

    async def test_parallel_identical_posts_create_one_capture(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(4)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id = %s", (body["capture_id"],)), 1)

    async def test_invalid_values_are_422_without_internals(self):
        _, assignment = await self.assignment()
        for values in ({**SYNTHETIC_VALUES, "unidades": "doce"}, {**SYNTHETIC_VALUES, "tipo": "gamma"}, {k: v for k, v in SYNTHETIC_VALUES.items() if k != "codigo_lote"},
                       {**SYNTHETIC_VALUES, "machine_code": "MP3"}):
            with self.subTest(values=values):
                reply = await self.post(self.payload(assignment, values=values))
                self.assertEqual((reply.status, reply.json()["code"]), (422, "CAPTURE_VALIDATION"))
                self.assertNotIn("SELECT", reply.text)

    async def test_the_payload_stays_closed_and_context_is_never_client_supplied(self):
        _, assignment = await self.assignment()
        for extra in ({"machine_code": "MP1"}, {"operating_date": "2026-01-01"}, {"work_order_id": str(uuid4())}, {"form_version_id": str(uuid4())}):
            reply = await self.post({**self.payload(assignment), **extra})
            self.assertEqual(reply.status, 422, extra)

    async def test_only_operacion_may_capture_and_anonymous_is_401(self):
        _, assignment = await self.assignment()
        self.assertEqual((await call("POST", "/api/captures", json_body=self.payload(assignment))).status, 401)
        for profile in ("JEFATURA", "SUPERVISION", "CALIDAD"):
            if profile in self.users:
                self.assertEqual((await self.post(self.payload(assignment), profile)).status, 403, profile)

    async def test_a_user_without_a_sector_grant_cannot_capture_and_nothing_is_written(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.capture")
        reply = await self.post(self.payload(assignment), "OPERACION_SIN_SECTOR")
        self.assertEqual(reply.status, 404)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture"), before)

    async def test_a_quality_area_code_is_not_a_production_capture(self):
        install_production_form(self.connection, SYNTHETIC_QUALITY_CODE, area="quality")
        _, assignment = await self.assignment()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", ENABLED | {SYNTHETIC_QUALITY_CODE}):
            reply = await self.post(self.payload(assignment, form_code=SYNTHETIC_QUALITY_CODE, values={}))
            self.assertEqual((reply.status, reply.json()["code"]), (409, "FORM_NOT_AVAILABLE"))


class ReadTests(MultiformApiCase):
    async def seed(self):
        _, assignment = await self.assignment()
        f6 = (await self.post(self.payload(assignment, form_code=F6))).json()["capture"]
        second = (await self.post(self.payload(assignment))).json()["capture"]
        return f6, second

    async def test_get_by_id_resolves_each_form(self):
        f6, second = await self.seed()
        for capture, code in ((f6, F6), (second, SYNTHETIC_CODE)):
            reply = await self.get(f"/api/captures/{capture['id']}")
            self.assertEqual(reply.status, 200)
            self.assertEqual((reply.json()["id"], reply.json()["form"]["code"]), (capture["id"], code))

    async def test_the_default_list_is_the_historic_f6_list(self):
        f6, second = await self.seed()
        listed = (await self.get("/api/captures")).json()
        self.assertIn(f6["id"], [c["id"] for c in listed])
        self.assertNotIn(second["id"], [c["id"] for c in listed])
        self.assertEqual({c["form"]["code"] for c in listed}, {F6})

    async def test_the_form_code_filter(self):
        f6, second = await self.seed()
        listed = (await self.get(f"/api/captures?form_code={SYNTHETIC_CODE}")).json()
        self.assertIn(second["id"], [c["id"] for c in listed])
        self.assertEqual({c["form"]["code"] for c in listed}, {SYNTHETIC_CODE})
        self.assertEqual({c["form"]["code"] for c in (await self.get(f"/api/captures?form_code={F6}")).json()}, {F6})
        both = (await self.get(f"/api/captures?form_code={SYNTHETIC_CODE}&machine_code=MP3")).json()
        self.assertEqual(both, [])

    async def test_a_disabled_or_unknown_form_code_is_422_not_an_empty_list(self):
        await self.seed()
        for code in ("VINTO-P1-10", "VINTO-P1-03", "nope", SYNTHETIC_QUALITY_CODE):
            reply = await self.get(f"/api/captures?form_code={code}")
            self.assertEqual((reply.status, reply.json()["code"]), (422, "UNSUPPORTED_FORM"), code)
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6})):
            self.assertEqual((await self.get(f"/api/captures?form_code={SYNTHETIC_CODE}")).status, 422)
        self.assertEqual((await self.get("/api/captures?form_code=" + "x" * 65)).status, 422)

    async def test_a_capture_of_a_form_that_is_not_enabled_is_404(self):
        _, second = await self.seed()
        with patch.object(_capture_service, "CENTRAL_FORM_CODES", frozenset({F6})):
            self.assertEqual((await self.get(f"/api/captures/{second['id']}")).status, 404)

    async def test_reads_respect_the_sector_scope_and_the_permission(self):
        f6, second = await self.seed()
        self.assertEqual((await self.get(f"/api/captures/{second['id']}", "OPERACION_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.get(f"/api/captures/{f6['id']}", "OPERACION_SIN_SECTOR")).status, 404)
        self.assertEqual((await self.get(f"/api/captures?form_code={SYNTHETIC_CODE}", "OPERACION_SIN_SECTOR")).json(), [])
        self.assertEqual((await self.get("/api/captures", "OPERACION_SIN_SECTOR")).json(), [])
        self.assertEqual((await call("GET", f"/api/captures/{second['id']}")).status, 401)
        self.assertEqual((await call("GET", f"/api/captures?form_code={SYNTHETIC_CODE}")).status, 401)
        for profile in ("JEFATURA", "SUPERVISION"):
            self.assertEqual((await self.get(f"/api/captures/{second['id']}", profile)).status, 403, profile)
            self.assertEqual((await self.get(f"/api/captures?form_code={SYNTHETIC_CODE}", profile)).status, 403, profile)

    async def test_malformed_ids_are_404_and_count_still_works(self):
        for value in (str(uuid4()), "no-es-un-uuid"):
            self.assertEqual((await self.get(f"/api/captures/{value}")).status, 404)
        self.assertEqual((await self.get("/api/captures/count?front=Bobinas")).status, 200)


if __name__ == "__main__":
    unittest.main()
