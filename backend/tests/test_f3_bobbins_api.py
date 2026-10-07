"""HTTP contract of POST/GET /api/bobbins for F3 (VINTO-P1-03): permissions, closed payload, response shape, error mapping, idempotency.

The ASGI app is called directly with DATABASE_URL patched to an ephemeral *_test database.
"""

import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from test_assignments_api import PROFILES, call, order_body
except ModuleNotFoundError:
    from tests.test_assignments_api import PROFILES, call, order_body

STATE = {}
VALUES = {"hora_inicio": "07:15", "hora_fin": "08:40", "diametro": "1200.5", "peso_kg": "845.25", "numero_de_cortes": "3", "observaciones": "ok"}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_f3api_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class BobbinApiCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_f3api")
        cls.connection = connect(cls.database)
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.users, cls.cookies = {}, {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (create_user(cls.connection, username=f"f3api.{profile.lower()}", display_name=profile.title(), profile_code=profile, password=password), password)

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
        body = {"capture_id": str(uuid4()), "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(VALUES)}
        body.update(changes)
        return body

    async def post(self, body, profile="OPERACION"):
        return await call("POST", "/api/bobbins", json_body=body, cookie=await self.cookie(profile))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]


class WriteTests(BobbinApiCase):
    async def test_unauthenticated_is_401(self):
        _, assignment = await self.assignment()
        self.assertEqual((await call("POST", "/api/bobbins", json_body=self.payload(assignment))).status, 401)
        self.assertEqual((await call("GET", f"/api/bobbins/{uuid4()}")).status, 401)

    async def test_only_operacion_registers_bobbins(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.bobbin")  # the database is shared by the tests of this class
        for profile in ("JEFATURA", "SUPERVISION", "CALIDAD", "DATA_BALTREK"):
            self.assertEqual((await self.post(self.payload(assignment), profile)).status, 403, profile)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), before)
        self.assertEqual((await self.post(self.payload(assignment), "OPERACION")).status, 201)

    async def test_response_exposes_capture_bobbin_and_code(self):
        order, assignment = await self.assignment("MP1")
        last = self.scalar("""SELECT coalesce(max(sequence_number),0) FROM vinto_txn.bobbin b JOIN vinto_master.machine m ON m.id=b.machine_id WHERE m.code='MP1'""")
        reply = await self.post(self.payload(assignment))
        self.assertEqual(reply.status, 201)
        data = reply.json()
        self.assertEqual((data["created"], data["already_submitted"]), (True, False))
        bobbin, capture = data["bobbin"], data["capture"]
        self.assertEqual((bobbin["capture_id"], bobbin["code"], bobbin["sequence_number"], bobbin["quality_status"]), (capture["id"], str(last + 1), last + 1, "pending"))
        self.assertEqual((bobbin["machine"]["code"], capture["form"]["code"], capture["revision"], capture["status"]), ("MP1", "VINTO-P1-03", 1, "submitted"))
        self.assertEqual((bobbin["diameter_mm"], bobbin["weight_kg"], bobbin["start_time"], bobbin["end_time"]), ("1200.5", "845.25", "07:15:00", "08:40:00"))
        self.assertEqual(set(capture["values"]), set(VALUES))
        self.assertEqual(capture["assignment"]["id"], assignment["id"])
        self.assertEqual(capture["work_order"]["number"], order["number"])
        self.assertEqual(bobbin["article"]["code"], capture["line"]["article"]["code"])
        self.assertNotIn("created_by", reply.body.decode() if hasattr(reply, "body") else "")
        got = await call("GET", f"/api/bobbins/{bobbin['id']}", cookie=await self.cookie("OPERACION"))
        self.assertEqual((got.status, got.json()), (200, bobbin))

    async def test_derived_fields_and_unknown_fields_are_rejected(self):
        _, assignment = await self.assignment()
        for extra in ("fecha", "turno", "maquina", "operador", "codigo_de_bobina", "gramaje", "descripcion_producto", "operating_date"):
            body = self.payload(assignment)
            body["values"][extra] = "x"
            self.assertEqual((await self.post(body)).status, 422, extra)
        for top in ("form_code", "machine", "revision", "status", "code", "operating_date"):
            self.assertEqual((await self.post({**self.payload(assignment), top: "x"})).status, 422, top)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), 0)

    async def test_invalid_values_are_422_and_write_nothing(self):
        _, assignment = await self.assignment()
        for changes in ({"hora_inicio": "99:00"}, {"peso_kg": "abc"}, {"peso_kg": "-1"}, {"numero_de_cortes": ""}):
            body = self.payload(assignment)
            body["values"].update(changes)
            self.assertEqual((await self.post(body)).status, 422, changes)
        body = self.payload(assignment)
        del body["values"]["peso_kg"]
        self.assertEqual((await self.post(body)).status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.capture c JOIN vinto_txn.assignment a ON a.id=c.assignment_id WHERE a.id=%s", (assignment["id"],)), 0)

    async def test_finished_assignment_is_409_and_unknown_is_404(self):
        _, assignment = await self.assignment()
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE id=%s", (assignment["id"],))
        reply = await self.post(self.payload(assignment))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))
        self.assertEqual((await self.post(self.payload({"id": str(uuid4())}))).status, 404)

    async def test_retry_is_200_with_the_same_bobbin_and_conflict_is_409(self):
        _, assignment = await self.assignment()
        body = self.payload(assignment)
        first = (await self.post(body)).json()
        again = await self.post(body)
        self.assertEqual(again.status, 200)
        self.assertEqual((again.json()["already_submitted"], again.json()["bobbin"]), (True, first["bobbin"]))
        changed = {**body, "values": {**VALUES, "peso_kg": "1"}}
        conflict = await self.post(changed)
        self.assertEqual((conflict.status, conflict.json()["code"]), (409, "CAPTURE_IDEMPOTENCY_CONFLICT"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin WHERE source_capture_id=%s", (body["capture_id"],)), 1)

    async def test_numbering_per_machine_through_http(self):
        _, mp1 = await self.assignment("MP1")
        a = int((await self.post(self.payload(mp1))).json()["bobbin"]["code"])
        b = int((await self.post(self.payload(mp1))).json()["bobbin"]["code"])
        _, mp3 = await self.assignment("MP3")
        c = (await self.post(self.payload(mp3))).json()["bobbin"]
        self.assertEqual(b, a + 1)
        self.assertEqual((c["machine"]["code"], c["code"]), ("MP3", "1"))  # MP3 only registered here: its own sequence starts at 1

    async def test_f6_endpoint_still_refuses_f3_and_f3_is_not_listed_as_f6(self):
        _, assignment = await self.assignment()
        self.assertEqual((await self.post(self.payload(assignment))).status, 201)
        f6 = {"capture_id": str(uuid4()), "form_code": "VINTO-P1-03", "assignment_id": assignment["id"], "device_key": str(uuid4()), "values": dict(VALUES)}
        self.assertEqual((await call("POST", "/api/captures", json_body=f6, cookie=await self.cookie("OPERACION"))).status, 422)
        listing = await call("GET", "/api/captures", cookie=await self.cookie("OPERACION"))
        self.assertEqual([c for c in listing.json() if c["form"]["code"] != "VINTO-P1-06"], [])

    async def test_raw_values_are_not_coerced_by_pydantic_before_central_validation(self):
        _, assignment = await self.assignment()
        before = self.scalar("SELECT count(*) FROM vinto_txn.bobbin")
        bad = ({"diametro": True}, {"peso_kg": True}, {"diametro": [1200]}, {"peso_kg": {"v": 1}}, {"hora_inicio": 715}, {"hora_fin": ["08:40"]},
               {"hora_inicio": True}, {"numero_de_cortes": 3}, {"numero_de_cortes": ["3"]}, {"numero_de_cortes": True}, {"observaciones": ["x"]},
               {"observaciones": 5}, {"diametro": None})
        for changes in bad:
            body = self.payload(assignment)
            body["values"].update(changes)
            reply = await self.post(body)
            self.assertEqual(reply.status, 422, changes)
            self.assertEqual(reply.json()["code"], "CAPTURE_VALIDATION", changes)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.bobbin"), before)
        ok = self.payload(assignment)
        ok["values"].update({"diametro": 1200.5, "peso_kg": 845, "observaciones": None})  # JSON numbers are valid decimals; null observations are absent
        self.assertEqual((await self.post(ok)).status, 201)

    async def test_unknown_bobbin_is_404_with_its_own_code(self):
        reply = await call("GET", f"/api/bobbins/{uuid4()}", cookie=await self.cookie("OPERACION"))
        self.assertEqual((reply.status, reply.json()["code"], reply.json()["detail"]), (404, "BOBBIN_NOT_FOUND", "Bobina no encontrada"))
        reply = await call("GET", "/api/bobbins/not-a-uuid", cookie=await self.cookie("OPERACION"))
        self.assertEqual((reply.status, reply.json()["code"]), (404, "BOBBIN_NOT_FOUND"))


if __name__ == "__main__":
    unittest.main()
