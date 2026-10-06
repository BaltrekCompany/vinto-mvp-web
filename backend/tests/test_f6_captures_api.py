"""HTTP contract of POST/GET /api/captures for F6 (VINTO-P1-06): permissions, closed payload, response shape, error mapping, idempotency.

The ASGI app is called directly with DATABASE_URL patched to an ephemeral *_test database.
"""

import asyncio
import secrets
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import psycopg
from pydantic import SecretStr

from app import capture_service
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from test_assignments_api import PROFILES, call, order_body
except ModuleNotFoundError:
    from tests.test_assignments_api import PROFILES, call, order_body

STATE = {}
VALUES = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}
NEXT_DAY = datetime(2099, 1, 1, 16, 0, tzinfo=timezone.utc)


def setUpModule():
    STATE["template"] = build_reference_template("vinto_capapi_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class CaptureApiCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_capapi")
        cls.connection = connect(cls.database)
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.users, cls.cookies = {}, {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (create_user(cls.connection, username=f"capapi.{profile.lower()}", display_name=profile.title(), profile_code=profile, password=password), password)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")

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

    def payload(self, assignment, **changes):
        body = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-06", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(VALUES)}
        body.update(changes)
        return body

    async def post(self, body, profile="OPERACION"):
        return await call("POST", "/api/captures", json_body=body, cookie=await self.cookie(profile))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]


class WriteTests(CaptureApiCase):
    async def test_unauthenticated_is_401(self):
        _, assignment = await self.assignment()
        reply = await call("POST", "/api/captures", json_body=self.payload(assignment))
        self.assertEqual(reply.status, 401)
        self.assertEqual((await call("GET", "/api/captures")).status, 401)

    async def test_operacion_submits_and_the_response_has_the_agreed_shape(self):
        order, assignment = await self.assignment()
        body = self.payload(assignment)
        reply = await self.post(body)
        self.assertEqual(reply.status, 201)
        data = reply.json()
        self.assertEqual((data["created"], data["already_submitted"]), (True, False))
        capture = data["capture"]
        self.assertEqual(set(capture), {"id", "status", "revision", "captured_at", "submitted_at", "form", "machine", "shift", "operating_date",
                                        "assignment", "work_order", "line", "values"})
        self.assertEqual((capture["id"], capture["status"], capture["revision"]), (body["capture_id"], "submitted", 1))
        self.assertEqual(capture["form"], {"code": "VINTO-P1-06", "version_number": 1, "name": capture["form"]["name"]})
        self.assertEqual(capture["machine"]["code"], "MP1")
        self.assertEqual(capture["assignment"], {"id": assignment["id"]})
        self.assertEqual(capture["work_order"], {"id": order["id"], "number": order["number"]})
        self.assertEqual((capture["line"]["line_code"], capture["line"]["pv_reference"]), ("L1", "PV-1"))
        self.assertEqual(set(capture["line"]["article"]), {"code", "description"})
        self.assertEqual(capture["shift"]["code"], assignment["shift"]["code"])
        self.assertEqual(capture["operating_date"], assignment["operating_date"])
        self.assertEqual(capture["values"], {**VALUES, "peso_kg": "125.50"})  # decimals as text, no precision loss
        text = reply.text.lower()
        for internal in ("created_by", "device_id", "machine_id", "form_version_id", "request_id", "traceback", "select ", "psycopg"):
            self.assertNotIn(internal, text)
        self.assertNotIn(body["device_key"], text)

    async def test_only_operacion_may_capture(self):
        _, assignment = await self.assignment()
        for profile in ("JEFATURA", "SUPERVISION", "CALIDAD", "DATA_BALTREK"):
            reply = await self.post(self.payload(assignment), profile)
            self.assertEqual(reply.status, 403, profile)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id=%s", (assignment["id"],)), 0)

    async def test_the_payload_is_closed(self):
        _, assignment = await self.assignment()
        for extra in ("machine_code", "machine_id", "shift", "operating_date", "work_order_id", "pv_reference", "article_code", "line_id", "form_version_id",
                      "form_version", "revision", "status", "captured_at", "submitted_at", "user_id", "created_by"):
            reply = await self.post({**self.payload(assignment), extra: "x"})
            self.assertEqual(reply.status, 422, extra)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id=%s", (assignment["id"],)), 0)

    async def test_malformed_identifiers_and_forms_are_422(self):
        _, assignment = await self.assignment()
        for changes in ({"capture_id": "nope"}, {"capture_id": str(__import__("uuid").uuid1())}, {"assignment_id": "nope"}, {"device_key": "nope"},
                        {"values": []}, {"form_code": "VINTO-P1-03"}):
            self.assertEqual((await self.post(self.payload(assignment, **changes))).status, 422, changes)

    async def test_value_errors_are_422_and_list_fields_without_internals(self):
        _, assignment = await self.assignment()
        reply = await self.post(self.payload(assignment, values={**VALUES, "peso_kg": "abc", "extra": 1}))
        self.assertEqual(reply.status, 422)
        self.assertEqual(reply.json()["code"], "CAPTURE_VALIDATION")
        self.assertIn("peso_kg", reply.json()["detail"])
        self.assertNotIn("Traceback", reply.text)

    async def test_stale_assignment_is_a_safe_409(self):
        _, assignment = await self.assignment()
        with patch.object(capture_service, "_now", return_value=NEXT_DAY):
            reply = await self.post(self.payload(assignment))
        self.assertEqual(reply.status, 409)
        self.assertEqual(reply.json()["code"], "ASSIGNMENT_STALE")
        self.assertNotIn("SELECT", reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id=%s", (assignment["id"],)), 0)

    async def test_finished_or_unknown_assignment_is_rejected(self):
        _, assignment = await self.assignment()
        await call("POST", f"/api/assignments/{assignment['id']}/finish", cookie=await self.cookie("SUPERVISION"))
        reply = await self.post(self.payload(assignment))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))
        self.assertEqual((await self.post(self.payload(assignment, assignment_id=str(uuid4())))).status, 404)

    async def test_idempotent_retry_and_conflict(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        first = await self.post(body)
        before = self.scalar("SELECT count(*) FROM vinto_audit.audit_event")
        retry = await self.post(body)
        self.assertEqual((first.status, retry.status), (201, 200))
        self.assertEqual((retry.json()["created"], retry.json()["already_submitted"]), (False, True))
        self.assertEqual(retry.json()["capture"], first.json()["capture"])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_audit.audit_event"), before)
        conflict = await self.post({**body, "values": {**VALUES, "cantidad_fardos": 99}})
        self.assertEqual((conflict.status, conflict.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))

    async def test_parallel_identical_posts_create_one_capture(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        replies = await asyncio.gather(*[self.post(body) for _ in range(3)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 201])
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE id=%s", (body["capture_id"],)), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture_detail WHERE capture_id=%s", (body["capture_id"],)), 5)

    async def test_database_failure_is_a_safe_503(self):
        _, assignment = await self.assignment()
        with patch.object(capture_service, "submit_production_capture", side_effect=psycopg.OperationalError("connection to server at 10.0.0.1 failed")):
            reply = await self.post(self.payload(assignment))
        self.assertEqual(reply.status, 503)
        self.assertEqual(reply.json(), {"status": "error", "database": "unavailable"})
        self.assertNotIn("10.0.0.1", reply.text)


class ReadTests(CaptureApiCase):
    async def test_list_and_get_by_id(self):
        _, mp1 = await self.assignment("MP1")
        _, mp3 = await self.assignment("MP3")
        one, two = self.payload(mp1), self.payload(mp3)
        await self.post(one)
        await self.post(two)
        cookie = await self.cookie("OPERACION")
        listed = (await call("GET", "/api/captures", cookie=cookie)).json()
        self.assertEqual([c["id"] for c in listed][:2], [two["capture_id"], one["capture_id"]])
        filtered = (await call("GET", f"/api/captures?machine_code=MP3&assignment_id={mp3['id']}", cookie=cookie)).json()
        self.assertEqual([c["id"] for c in filtered], [two["capture_id"]])
        self.assertEqual(len((await call("GET", "/api/captures?limit=1", cookie=cookie)).json()), 1)
        for bad in ("limit=0", "limit=201", "operating_date=nope", "assignment_id=nope"):
            self.assertEqual((await call("GET", f"/api/captures?{bad}", cookie=cookie)).status, 422, bad)
        one_reply = await call("GET", f"/api/captures/{one['capture_id']}", cookie=cookie)
        self.assertEqual((one_reply.status, one_reply.json()["id"]), (200, one["capture_id"]))
        self.assertEqual((await call("GET", f"/api/captures/{uuid4()}", cookie=cookie)).status, 404)
        self.assertEqual((await call("GET", "/api/captures/not-a-uuid", cookie=cookie)).status, 404)

    async def test_reading_requires_the_capture_permission(self):
        for profile in ("JEFATURA", "SUPERVISION", "CALIDAD", "DATA_BALTREK"):
            self.assertEqual((await call("GET", "/api/captures", cookie=await self.cookie(profile))).status, 403, profile)

    async def test_count_keeps_working(self):
        reply = await call("GET", "/api/captures/count?front=Bobinas", cookie=await self.cookie("OPERACION"))
        self.assertEqual(reply.status, 200)


if __name__ == "__main__":
    unittest.main()
