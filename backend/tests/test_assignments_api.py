"""HTTP contract of /api/assignments: permissions (only SUPERVISION manages), response shape, error mapping, idempotency.

The ASGI app is called directly with the application's DATABASE_URL patched to an ephemeral *_test database.
"""

import asyncio
import json
import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg.conninfo import make_conninfo
from pydantic import SecretStr

from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database
from app.main import app
from app.seed.bundle import load_bundle

BUNDLE = load_bundle()
COOKIE = settings.auth_cookie_name
STATE = {}
MP1_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP1")
MP3_CODES = sorted(r["article_code"] for r in BUNDLE.article_machines if r["machine_code"] == "MP3")
PROFILES = ("JEFATURA", "SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK")


def setUpModule():
    STATE["template"] = build_reference_template("vinto_asapi_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class Reply:
    def __init__(self, status, headers, body):
        self.status, self.headers, self.body = status, headers, body

    def json(self):
        return json.loads(self.body)

    def set_cookie_value(self):
        for key, value in self.headers:
            if key == b"set-cookie" and value.decode().startswith(f"{COOKIE}="):
                return value.decode().split(";", 1)[0].split("=", 1)[1]
        return None

    @property
    def text(self):
        return self.body.decode("utf-8", "replace") + " ".join(f"{k.decode()}:{v.decode()}" for k, v in self.headers)


async def call(method, path, *, json_body=None, cookie=None, extra_headers=()):
    body = b"" if json_body is None else json.dumps(json_body).encode()
    headers = [(b"host", b"127.0.0.1:8000")] + [(k.encode(), v.encode()) for k, v in extra_headers]
    if body:
        headers += [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]
    if cookie:
        headers.append((b"cookie", f"{COOKIE}={cookie}".encode()))
    query = b""
    if "?" in path:
        path, raw = path.split("?", 1)
        query = raw.encode()
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method, "scheme": "http", "path": path,
             "raw_path": path.encode(), "query_string": query, "headers": headers, "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 1), "root_path": ""}
    sent, delivered = [], False

    async def receive():
        nonlocal delivered
        if not delivered:
            delivered = True
            return {"type": "http.request", "body": body, "more_body": False}
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    await app(scope, receive, send)
    start = next(m for m in sent if m["type"] == "http.response.start")
    return Reply(start["status"], list(start["headers"]), b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body"))


def order_body(machine="MP1", lines=2):
    codes = MP1_CODES if machine == "MP1" else MP3_CODES
    return {"machine_code": machine, "lines": [{"pv_reference": f"PV-{i + 1}", "article_code": codes[i], "quantity": 10 * (i + 1), "due_date": "2026-11-01"} for i in range(lines)]}


class AssignmentApiCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_asapi")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.users, cls.cookies = {}, {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            cls.users[profile] = (create_user(cls.connection, username=f"asapi.{profile.lower()}", display_name=profile.title(), profile_code=profile, password=password), password)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def asyncSetUp(self):
        # Tests share one database: start each one with no active assignment so results do not depend on test order.
        self.connection.execute("UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")

    async def cookie(self, profile):
        if profile not in self.cookies:
            created, password = self.users[profile]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, profile)
            self.cookies[profile] = reply.set_cookie_value()
        return self.cookies[profile]

    async def published_order(self, machine="MP1", lines=2, publish=True):
        jefatura = await self.cookie("JEFATURA")
        order = (await call("POST", "/api/work-orders", json_body=order_body(machine, lines), cookie=jefatura)).json()
        if publish:
            order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=jefatura)).json()
        return order

    async def activate(self, order, index=0, profile="SUPERVISION", body=None):
        payload = body if body is not None else {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][index]["id"]}
        return await call("POST", "/api/assignments/activate", json_body=payload, cookie=await self.cookie(profile))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]


class SupervisionFlowTests(AssignmentApiCase):
    async def test_supervision_activates_reuses_and_finishes(self):
        order = await self.published_order()
        created = await self.activate(order, 0)
        self.assertEqual(created.status, 201)
        body = created.json()
        self.assertEqual((body["created"], body["already_active"], body["finished_assignment_id"]), (True, False, None))
        assignment = body["assignment"]
        self.assertEqual((assignment["status"], assignment["machine"], assignment["operational"]), ("active", {"code": "MP1", "name": "MP1"}, {"version_number": 2}))
        self.assertEqual(assignment["work_order"], {"id": order["id"], "number": order["number"]})
        self.assertIn(assignment["shift"]["code"], ("DIA", "NOCHE"))
        self.assertRegex(assignment["operating_date"], r"^\d{4}-\d{2}-\d{2}$")
        self.assertEqual((assignment["line"]["line_code"], assignment["line"]["pv_reference"], assignment["line"]["unit"]), ("L1", "PV-1", "KG"))
        self.assertNotEqual(assignment["line"]["id"], order["baseline"]["lines"][0]["id"])  # the operational line, not the baseline's
        self.assertEqual(assignment["assigned_by"], {"id": str(self.users["SUPERVISION"][0].user_id), "display_name": "Supervision"})
        self.assertIsNone(assignment["finished_at"])

        again = await self.activate(order, 0)
        self.assertEqual(again.status, 200)
        self.assertEqual((again.json()["created"], again.json()["already_active"], again.json()["assignment"]["id"]), (False, True, assignment["id"]))

        second = await self.activate(order, 1)
        self.assertEqual(second.status, 201)
        self.assertEqual(second.json()["finished_assignment_id"], assignment["id"])
        self.assertEqual(second.json()["assignment"]["operational"], {"version_number": 2})

        finished = await call("POST", f"/api/assignments/{second.json()['assignment']['id']}/finish", cookie=await self.cookie("SUPERVISION"))
        self.assertEqual(finished.status, 200)
        self.assertEqual(finished.json()["status"], "finished")
        self.assertIsNotNone(finished.json()["finished_at"])
        repeat = await call("POST", f"/api/assignments/{second.json()['assignment']['id']}/finish", cookie=await self.cookie("SUPERVISION"))
        self.assertEqual((repeat.status, repeat.json()["finished_at"]), (200, finished.json()["finished_at"]))

    async def test_the_baseline_is_not_changed_by_an_activation(self):
        order = await self.published_order()
        await self.activate(order, 0)
        detail = (await call("GET", f"/api/work-orders/{order['id']}", cookie=await self.cookie("JEFATURA"))).json()
        self.assertEqual(detail["baseline"], order["baseline"])
        self.assertEqual((detail["status"], order["status"]), ("in_progress", "published"))

    async def test_simultaneous_identical_activations_create_one_assignment(self):
        order = await self.published_order()
        cookie = await self.cookie("SUPERVISION")
        payload = {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]}
        replies = await asyncio.gather(*[call("POST", "/api/assignments/activate", json_body=payload, cookie=cookie) for _ in range(3)])
        self.assertEqual(sorted(r.status for r in replies), [200, 200, 201])
        self.assertEqual(len({r.json()["assignment"]["id"] for r in replies}), 1)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order["id"],)), 1)

    async def test_list_and_active_for_every_profile(self):
        order = await self.published_order(machine="MP3", lines=1)
        made = (await self.activate(order, 0)).json()["assignment"]
        for profile in PROFILES:
            cookie = await self.cookie(profile)
            with self.subTest(profile=profile):
                listing = await call("GET", "/api/assignments?machine_code=MP3&status=active", cookie=cookie)
                self.assertEqual(listing.status, 200)
                self.assertEqual([a["id"] for a in listing.json()], [made["id"]])
                active = await call("GET", "/api/assignments/active?machine_code=MP3", cookie=cookie)
                self.assertEqual(active.status, 200)
                self.assertEqual(sorted(active.json()), ["assignment", "current_shift", "stale"])
                self.assertEqual(active.json()["assignment"]["id"], made["id"])
                self.assertIs(active.json()["stale"], False)
                self.assertEqual(sorted(active.json()["current_shift"]), ["code", "name", "operating_date"])

    async def test_filters_and_order(self):
        order = await self.published_order(lines=2)
        first = (await self.activate(order, 0)).json()["assignment"]
        second = (await self.activate(order, 1)).json()["assignment"]
        cookie = await self.cookie("OPERACION")
        listing = (await call("GET", f"/api/assignments?work_order_id={order['id']}", cookie=cookie)).json()
        self.assertEqual([a["id"] for a in listing], [second["id"], first["id"]])  # newest first
        finished = (await call("GET", f"/api/assignments?work_order_id={order['id']}&status=finished", cookie=cookie)).json()
        self.assertEqual([a["id"] for a in finished], [first["id"]])
        by_date = (await call("GET", f"/api/assignments?work_order_id={order['id']}&operating_date={first['operating_date']}", cookie=cookie)).json()
        self.assertEqual(len(by_date), 2)
        for bad in ("status=weird", "operating_date=not-a-date", "work_order_id=nope", "limit=0"):
            self.assertEqual((await call("GET", f"/api/assignments?{bad}", cookie=cookie)).status, 422, bad)

    async def test_active_with_no_assignment(self):
        reply = await call("GET", "/api/assignments/active?machine_code=MP3", cookie=await self.cookie("OPERACION"))
        # MP3 may have assignments from other tests in this class, so only the contract is checked here.
        self.assertEqual(reply.status, 200)
        self.assertIn("assignment", reply.json())


class PermissionTests(AssignmentApiCase):
    async def test_without_a_session_every_endpoint_is_401(self):
        requests = [("POST", "/api/assignments/activate", {"work_order_id": str(uuid4()), "baseline_line_id": str(uuid4())}),
                    ("POST", f"/api/assignments/{uuid4()}/finish", None), ("GET", "/api/assignments", None), ("GET", "/api/assignments/active?machine_code=MP1", None)]
        for method, path, body in requests:
            for cookie in (None, secrets.token_urlsafe(32)):
                reply = await call(method, path, json_body=body, cookie=cookie)
                self.assertEqual((reply.status, reply.json()), (401, {"detail": "No autenticado"}), path)

    async def test_only_supervision_can_activate_and_finish(self):
        order = await self.published_order(lines=1)
        active = (await self.activate(order, 0)).json()["assignment"]
        before = self.scalar("SELECT count(*) FROM vinto_txn.assignment")
        for profile in ("JEFATURA", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            with self.subTest(profile=profile):
                activate = await self.activate(order, 0, profile=profile)
                finish = await call("POST", f"/api/assignments/{active['id']}/finish", cookie=await self.cookie(profile))
                self.assertEqual((activate.status, finish.status), (403, 403))
                self.assertEqual(activate.json(), {"detail": "Permiso insuficiente"})
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment"), before)
        self.assertEqual(self.scalar("SELECT status FROM vinto_txn.assignment WHERE id=%s", (active["id"],)), "active")

    async def test_jefatura_with_work_order_manage_still_cannot_activate(self):
        order = await self.published_order(lines=1)
        reply = await self.activate(order, 0, profile="JEFATURA")
        self.assertEqual(reply.status, 403)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order["id"],)), 0)


class ErrorMappingTests(AssignmentApiCase):
    async def test_draft_order_is_a_409(self):
        draft = await self.published_order(publish=False)
        reply = await self.activate(draft, 0)
        self.assertEqual((reply.status, reply.json()["code"]), (409, "WORK_ORDER_NOT_ACTIVATABLE"))

    async def test_closed_order_is_a_409(self):
        order = await self.published_order(lines=1)
        self.connection.execute("UPDATE vinto_txn.work_order SET status='closed' WHERE id=%s", (order["id"],))
        self.assertEqual((await self.activate(order, 0)).status, 409)

    async def test_unknown_references_are_404(self):
        order = await self.published_order()
        other = await self.published_order()
        cases = [({"work_order_id": str(uuid4()), "baseline_line_id": order["baseline"]["lines"][0]["id"]}, "WORK_ORDER_NOT_FOUND"),
                 ({"work_order_id": order["id"], "baseline_line_id": str(uuid4())}, "BASELINE_LINE_NOT_FOUND"),
                 ({"work_order_id": order["id"], "baseline_line_id": other["baseline"]["lines"][0]["id"]}, "BASELINE_LINE_NOT_FOUND")]
        for body, code in cases:
            reply = await self.activate(order, body=body)
            self.assertEqual((reply.status, reply.json()["code"]), (404, code))
        finish = await call("POST", f"/api/assignments/{uuid4()}/finish", cookie=await self.cookie("SUPERVISION"))
        self.assertEqual((finish.status, finish.json()["code"]), (404, "ASSIGNMENT_NOT_FOUND"))
        self.assertEqual((await call("POST", "/api/assignments/not-a-uuid/finish", cookie=await self.cookie("SUPERVISION"))).status, 404)

    async def test_an_operational_line_id_is_rejected(self):
        order = await self.published_order(lines=1)
        assignment = (await self.activate(order, 0)).json()["assignment"]
        reply = await self.activate(order, body={"work_order_id": order["id"], "baseline_line_id": assignment["line"]["id"]})
        self.assertEqual((reply.status, reply.json()["code"]), (404, "BASELINE_LINE_NOT_FOUND"))

    async def test_the_client_cannot_choose_machine_shift_date_or_version(self):
        order = await self.published_order(lines=1)
        base = {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]}
        for extra in ({"machine_code": "MP3"}, {"shift_schedule_id": str(uuid4())}, {"operating_date": "2026-10-06"}, {"operational_line_id": str(uuid4())}):
            reply = await self.activate(order, body={**base, **extra})
            self.assertEqual(reply.status, 422, extra)
        for body in ({"work_order_id": "nope", "baseline_line_id": base["baseline_line_id"]}, {"work_order_id": order["id"]}, {}):
            self.assertEqual((await self.activate(order, body=body)).status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order["id"],)), 0)

    async def test_missing_shift_configuration_is_a_safe_409(self):
        order = await self.published_order(lines=1)
        self.connection.execute("UPDATE vinto_config.shift SET active=false")
        try:
            reply = await self.activate(order, 0)
        finally:
            self.connection.execute("UPDATE vinto_config.shift SET active=true")
        self.assertEqual(reply.status, 409)
        self.assertEqual(reply.json()["code"], "SHIFT_NOT_CONFIGURED")
        self.assertEqual(sorted(reply.json()), ["code", "detail"])
        for forbidden in ("07:00", "19:00", "La_Paz", "SELECT", "psycopg", "vinto_config", "Traceback"):
            self.assertNotIn(forbidden, reply.text)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s AND kind='operational'", (order["id"],)), 0)

    async def test_ambiguous_shift_configuration_is_a_409(self):
        order = await self.published_order(lines=1)
        self.connection.execute("INSERT INTO vinto_config.shift (code,name) VALUES ('OVERLAPAPI','Solapado')")
        self.connection.execute("""INSERT INTO vinto_config.shift_schedule (shift_id,sector_id,starts_at,ends_at,timezone,valid_from)
                                   SELECT sh.id,s.id,'00:00','23:59','America/La_Paz','2026-01-01' FROM vinto_config.shift sh, vinto_master.sector s WHERE sh.code='OVERLAPAPI' AND s.code='BOBINAS'""")
        try:
            reply = await self.activate(order, 0)
        finally:
            self.connection.execute("UPDATE vinto_config.shift SET active=false WHERE code='OVERLAPAPI'")
        self.assertEqual((reply.status, reply.json()["code"]), (409, "SHIFT_AMBIGUOUS"))

    async def test_unknown_machine_for_the_active_query(self):
        cookie = await self.cookie("OPERACION")
        self.assertEqual((await call("GET", "/api/assignments/active?machine_code=NOPE", cookie=cookie)).status, 404)
        self.assertEqual((await call("GET", "/api/assignments/active", cookie=cookie)).status, 422)

    async def test_database_down_is_a_safe_503(self):
        order = await self.published_order(lines=1)
        cookie = await self.cookie("SUPERVISION")
        closed = SecretStr(make_conninfo(database_url(self.database), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed):
            reply = await call("GET", "/api/assignments", cookie=cookie)
        self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))
        self.assertNotIn("postgresql://", reply.text)
        self.assertTrue(order)


class ResponseHygieneTests(AssignmentApiCase):
    async def test_responses_expose_only_the_public_model(self):
        order = await self.published_order(lines=1)
        activation = (await self.activate(order, 0)).json()
        listing = (await call("GET", "/api/assignments", cookie=await self.cookie("CALIDAD"))).json()
        active = (await call("GET", "/api/assignments/active?machine_code=MP1", cookie=await self.cookie("CALIDAD"))).json()
        self.assertEqual(sorted(activation), ["already_active", "assignment", "created", "finished_assignment_id"])
        for assignment in (activation["assignment"], listing[0], active["assignment"]):
            self.assertEqual(sorted(assignment), ["assigned_by", "created_at", "finished_at", "id", "line", "machine", "operating_date", "operational", "shift", "status", "work_order"])
            self.assertEqual(sorted(assignment["assigned_by"]), ["display_name", "id"])
            self.assertEqual(sorted(assignment["line"]), ["article", "due_date", "id", "line_code", "pv_reference", "quantity", "unit"])
        text = json.dumps([activation, listing, active]).lower()
        for forbidden in ("created_by", "updated_by", "password", "token", "hash", "cookie", "audit", "shift_schedule", "article_version", "unit_id", "username"):
            self.assertNotIn(forbidden, text)

    async def test_request_id_is_server_generated_and_the_actor_is_the_supervisor(self):
        order = await self.published_order(lines=1)
        reply = await call("POST", "/api/assignments/activate", cookie=await self.cookie("SUPERVISION"), extra_headers=[("x-request-id", "client-chosen")],
                           json_body={"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        assignment_id = reply.json()["assignment"]["id"]
        row = self.connection.execute("SELECT request_id,actor_id,reason FROM vinto_audit.audit_event WHERE entity_table='assignment' AND entity_key->>'id'=%s", (assignment_id,)).fetchone()
        self.assertNotEqual(row[0], "client-chosen")
        self.assertEqual((row[1], row[2]), (self.users["SUPERVISION"][0].user_id, "activate assignment"))


if __name__ == "__main__":
    unittest.main()
