"""HTTP contract of /api/work-orders: permissions per profile, validation, error mapping and response shape.

The ASGI app is called directly. The application's DATABASE_URL is patched to an ephemeral *_test database
(verified through connect_test_database). Passwords are generated per run; nothing touches vinto.
"""

import asyncio
import json
import secrets
import unittest
from datetime import date
from unittest.mock import patch
from uuid import UUID, uuid4

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
    STATE["template"] = build_reference_template("vinto_woapi_tpl")


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


def payload(machine="MP1", lines=None):
    return {"machine_code": machine, "lines": lines or [{"pv_reference": "PV-001", "article_code": MP1_CODES[0], "quantity": 100, "due_date": "2026-10-30"}]}


def line_body(code=None, pv="PV-002", quantity=10, due="2026-11-05"):
    return {"pv_reference": pv, "article_code": code or MP1_CODES[1], "quantity": quantity, "due_date": due}


class WorkOrderApiCase(unittest.IsolatedAsyncioTestCase):
    cookies: dict

    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_woapi")
        cls.connection = connect(cls.database)  # guarded: current_database() must end in _test
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.users = {}
        for profile in PROFILES:
            password = "pw-" + secrets.token_urlsafe(18)
            created = create_user(cls.connection, username=f"woapi.{profile.lower()}", display_name=profile.title(), profile_code=profile, password=password, sectors=("BOBINAS",))
            cls.users[profile] = (created, password)
        cls.cookies = {}

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def cookie(self, profile):
        if profile not in self.cookies:
            created, password = self.users[profile]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, profile)
            self.cookies[profile] = reply.set_cookie_value()
        return self.cookies[profile]

    async def create(self, profile="JEFATURA", body=None):
        return await call("POST", "/api/work-orders", json_body=body or payload(), cookie=await self.cookie(profile))

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]


class SupervisionRevisionNoticesTests(WorkOrderApiCase):
    """E2-C2 end-to-end against a disposable PostgreSQL 17 test database."""

    async def _reprogram(self, order, *, expected_version=1, quantity=120):
        original = order["programming"]["lines"][0] if order.get("programming") else order["baseline"]["lines"][0]
        fields = {
            "pv_reference": original["pv_reference"], "article_code": original["article"]["code"],
            "quantity": original["quantity"], "due_date": original["due_date"],
        }
        reply = await call(
            "POST", f"/api/work-orders/{order['id']}/lines/L1/reprogram",
            json_body={"expected_version": expected_version, "expected": fields,
                       "replacement": {**fields, "quantity": quantity},
                       "reason": "Ajuste autorizado por Jefatura para QA"},
            cookie=await self.cookie("JEFATURA"))
        self.assertEqual(reply.status, 200, reply.text)
        return reply.json()

    async def _create_revision(self):
        initial = (await self.create()).json()
        published = (await call("POST", f"/api/work-orders/{initial['id']}/publish",
                                cookie=await self.cookie("JEFATURA"))).json()
        return await self._reprogram(published)

    async def _notice(self, order, cookie=None):
        resp = await call("GET", "/api/work-orders/supervision-revision-notices",
                          cookie=cookie or await self.cookie("SUPERVISION"))
        self.assertEqual(resp.status, 200, resp.text)
        self.assertEqual(dict(resp.headers).get(b"cache-control"), b"private, no-store")
        return next((n for n in resp.json() if n["work_order_id"] == order["id"]), None)

    async def test_revision_notice_before_assignment_receipt_idempotency_and_audit(self):
        order = await self._create_revision()
        notice = await self._notice(order)
        self.assertIsNotNone(notice)
        self.assertEqual(notice["version_number"], 2)
        self.assertEqual(notice["status"], "published")
        self.assertEqual(notice["line_code"], "L1")
        self.assertEqual(notice["work_order_number"], order["number"])
        self.assertEqual(notice["machine_code"], "MP1")
        self.assertEqual(notice["reason"], "Ajuste autorizado por Jefatura para QA")
        self.assertEqual(notice["before"]["quantity"], "100")
        self.assertEqual(notice["after"]["quantity"], "120")
        self.assertIsNone(notice["acknowledged_at"])

        url = f"/api/work-orders/{order['id']}/acknowledge-supervision-revision"
        cookie = await self.cookie("SUPERVISION")
        old = await call("POST", url, json_body={"expected_version": 1}, cookie=cookie)
        self.assertEqual((old.status, old.json()["code"]), (409, "SUPERVISION_REVISION_CHANGED"))

        for injected in ({"user_id": str(uuid4())}, {"version_id": str(uuid4())},
                         {"machine_code": "MP1"}, {"acknowledged_at": "2020-01-01T00:00:00Z"}):
            bad = await call("POST", url, json_body={"expected_version": 2, **injected}, cookie=cookie)
            self.assertEqual(bad.status, 422)

        first = await call("POST", url, json_body={"expected_version": 2}, cookie=cookie)
        self.assertEqual(first.status, 200, first.text)
        repeated = await call("POST", url, json_body={"expected_version": 2}, cookie=cookie)
        self.assertEqual(repeated.status, 200, repeated.text)
        self.assertEqual(first.json(), repeated.json())

        version_id = self.scalar(
            "SELECT id FROM vinto_txn.work_order_version WHERE work_order_id=%s AND version_number=2",
            (order["id"],))
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_supervision_revision_receipt WHERE version_id=%s",
            (version_id,)), 1)
        actor, reason = self.connection.execute(
            """SELECT actor_id, reason FROM vinto_audit.audit_event
               WHERE entity_table='work_order_supervision_revision_receipt'
                 AND action='INSERT' AND new_data->>'version_id'=%s""",
            (str(version_id),)).fetchone()
        self.assertEqual(actor, self.users["SUPERVISION"][0].user_id)
        self.assertEqual(reason, "supervisor acknowledged current published OT revision")

        afterward = await self._notice(order)
        self.assertEqual(afterward["acknowledged_at"], first.json()["acknowledged_at"])
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.assignment a "
            "JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id "
            "JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id "
            "WHERE v.work_order_id=%s", (order["id"],)), 0)

        import psycopg
        rid = self.scalar(
            "SELECT id FROM vinto_txn.work_order_supervision_revision_receipt WHERE version_id=%s",
            (version_id,))
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute(
                "UPDATE vinto_txn.work_order_supervision_revision_receipt SET acknowledged_at=clock_timestamp() WHERE id=%s",
                (rid,))
        with self.assertRaises(psycopg.errors.CheckViolation):
            self.connection.execute(
                "DELETE FROM vinto_txn.work_order_supervision_revision_receipt WHERE id=%s",
                (rid,))

    async def test_newer_revision_requires_new_ack_without_erasing_prior_receipt(self):
        order = await self._create_revision()
        cookie = await self.cookie("SUPERVISION")
        url = f"/api/work-orders/{order['id']}/acknowledge-supervision-revision"
        first = await call("POST", url, json_body={"expected_version": 2}, cookie=cookie)
        self.assertEqual(first.status, 200, first.text)

        latest = await self._reprogram(order, expected_version=2, quantity=130)
        new_notice = await self._notice(latest)
        self.assertEqual(new_notice["version_number"], 3)
        self.assertIsNone(new_notice["acknowledged_at"])
        self.assertEqual(new_notice["before"]["quantity"], "120")
        self.assertEqual(new_notice["after"]["quantity"], "130")
        stale = await call("POST", url, json_body={"expected_version": 2}, cookie=cookie)
        self.assertEqual((stale.status, stale.json()["code"]), (409, "SUPERVISION_REVISION_CHANGED"))
        third = await call("POST", url, json_body={"expected_version": 3}, cookie=cookie)
        self.assertEqual(third.status, 200, third.text)
        self.assertEqual(self.scalar(
            """SELECT count(*) FROM vinto_txn.work_order_supervision_revision_receipt r
               JOIN vinto_txn.work_order_version v ON v.id=r.version_id
               WHERE v.work_order_id=%s AND r.user_id=%s""",
            (order["id"], self.users["SUPERVISION"][0].user_id)), 2)

    async def test_permissions_unrevised_and_archived_orders_fail_closed(self):
        base = (await self.create()).json()
        published = (await call("POST", f"/api/work-orders/{base['id']}/publish",
                                cookie=await self.cookie("JEFATURA"))).json()
        url = f"/api/work-orders/{published['id']}/acknowledge-supervision-revision"
        cookie = await self.cookie("SUPERVISION")
        no_change = await call("POST", url, json_body={"expected_version": 1}, cookie=cookie)
        self.assertEqual(no_change.status, 404)

        for role in ("JEFATURA", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            wrong = await call("GET", "/api/work-orders/supervision-revision-notices",
                               cookie=await self.cookie(role))
            self.assertEqual(wrong.status, 403, role)
            cannot_ack = await call("POST", url, json_body={"expected_version": 1},
                                    cookie=await self.cookie(role))
            self.assertEqual(cannot_ack.status, 403, role)
        self.assertEqual((await call("GET", "/api/work-orders/supervision-revision-notices")).status, 401)

        revised = await self._reprogram(published)
        self.assertIsNotNone(await self._notice(revised))
        archived = await call("POST", f"/api/work-orders/{revised['id']}/archive",
                              json_body={"reason": "Retiro de OT ficticia durante QA"},
                              cookie=await self.cookie("JEFATURA"))
        self.assertEqual(archived.status, 200, archived.text)
        self.assertIsNone(await self._notice(revised))
        denied = await call("POST", f"/api/work-orders/{revised['id']}/acknowledge-supervision-revision",
                            json_body={"expected_version": 2}, cookie=cookie)
        self.assertEqual(denied.status, 404)


class JefaturaFlowTests(WorkOrderApiCase):
    async def test_jefatura_creates_adds_a_line_publishes_and_everybody_can_read_it(self):
        created = await self.create()
        self.assertEqual(created.status, 201)
        order = created.json()
        self.assertRegex(order["number"], r"^OT-\d{4}-\d{4}$")
        self.assertEqual((order["status"], order["machine"], order["baseline"]["version_number"]), ("draft", {"code": "MP1", "name": "MP1"}, 1))
        self.assertIsNone(order["baseline"]["published_at"])
        first = order["baseline"]["lines"][0]
        self.assertEqual((first["line_code"], first["pv_reference"], first["quantity"], first["unit"], first["due_date"]), ("L1", "PV-001", 100, "KG", "2026-10-30"))
        self.assertEqual(first["article"]["code"], MP1_CODES[0])
        self.assertTrue(first["article"]["description"])

        added = await call("POST", f"/api/work-orders/{order['id']}/lines", json_body=line_body(), cookie=await self.cookie("JEFATURA"))
        self.assertEqual(added.status, 201)
        self.assertEqual([l["line_code"] for l in added.json()["baseline"]["lines"]], ["L1", "L2"])

        published = await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))
        self.assertEqual(published.status, 200)
        body = published.json()
        self.assertEqual(body["status"], "published")
        self.assertIsNotNone(body["baseline"]["published_at"])

        for profile in PROFILES:
            detail = await call("GET", f"/api/work-orders/{order['id']}", cookie=await self.cookie(profile))
            self.assertEqual((profile, detail.status, detail.json()), (profile, 200, body))

    async def test_publish_is_idempotent_over_http(self):
        order = (await self.create()).json()
        first = await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))
        second = await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))
        self.assertEqual((first.status, second.status), (200, 200))
        self.assertEqual(first.json(), second.json())

    async def test_adding_a_line_after_publication_is_a_409(self):
        order = (await self.create()).json()
        await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))
        reply = await call("POST", f"/api/work-orders/{order['id']}/lines", json_body=line_body(), cookie=await self.cookie("JEFATURA"))
        self.assertEqual(reply.status, 409)
        self.assertEqual(reply.json()["code"], "WORK_ORDER_ALREADY_PUBLISHED")
        detail = await call("GET", f"/api/work-orders/{order['id']}", cookie=await self.cookie("JEFATURA"))
        self.assertEqual(len(detail.json()["baseline"]["lines"]), 1)

    async def test_list_filters_and_order(self):
        mp3 = (await self.create(body=payload("MP3", [{"pv_reference": "PV-M3", "article_code": MP3_CODES[0], "quantity": 5, "due_date": "2026-10-31"}]))).json()
        mp1 = (await self.create()).json()
        await call("POST", f"/api/work-orders/{mp1['id']}/publish", cookie=await self.cookie("JEFATURA"))
        cookie = await self.cookie("OPERACION")
        everything = (await call("GET", "/api/work-orders", cookie=cookie)).json()
        numbers = [o["number"] for o in everything]
        self.assertEqual(numbers, sorted(numbers, reverse=True))  # newest first
        self.assertLess(numbers.index(mp1["number"]), numbers.index(mp3["number"]))
        only_mp3 = (await call("GET", "/api/work-orders?machine_code=MP3", cookie=cookie)).json()
        self.assertTrue(only_mp3 and all(o["machine"]["code"] == "MP3" for o in only_mp3))
        published = (await call("GET", "/api/work-orders?status=published", cookie=cookie)).json()
        self.assertTrue(published and all(o["status"] == "published" for o in published))
        self.assertEqual((await call("GET", "/api/work-orders?status=weird", cookie=cookie)).status, 422)
        self.assertEqual((await call("GET", "/api/work-orders?limit=0", cookie=cookie)).status, 422)

    async def test_numbers_are_distinct_for_simultaneous_requests(self):
        cookie = await self.cookie("JEFATURA")
        replies = await asyncio.gather(*[call("POST", "/api/work-orders", json_body=payload(), cookie=cookie) for _ in range(4)])
        self.assertEqual([r.status for r in replies], [201] * 4)
        self.assertEqual(len({r.json()["number"] for r in replies}), 4)


class DraftLineEditTests(WorkOrderApiCase):
    """E2-A: ediciones de borrador con MF13 y control de escritura concurrente."""

    async def test_edit_four_fields_keeps_machine_and_writes_audit(self):
        created = (await self.create()).json()
        original = created["baseline"]["lines"][0]
        expected = line_body(code=original["article"]["code"], pv=original["pv_reference"],
                             quantity=original["quantity"], due=original["due_date"])
        replacement = line_body(code=MP1_CODES[1], pv="PV-CORREGIDO", quantity=150, due="2026-12-15")
        url = f"/api/work-orders/{created['id']}/lines/L1/edit-draft"
        reply = await call("POST", url, json_body={"expected": expected, "replacement": replacement,
                                                  "reason": "Corrección de programación QA"},
                           cookie=await self.cookie("JEFATURA"))
        self.assertEqual(reply.status, 200, reply.text)
        updated = reply.json()
        item = updated["baseline"]["lines"][0]
        self.assertEqual((item["pv_reference"], item["article"]["code"], item["quantity"], item["due_date"]),
                         ("PV-CORREGIDO", MP1_CODES[1], 150, "2026-12-15"))
        self.assertEqual(item["machine"], original["machine"])
        self.assertEqual(item["id"], original["id"])
        self.assertEqual((updated["baseline"]["id"], updated["baseline"]["version_number"], updated["status"]),
                         (created["baseline"]["id"], 1, "draft"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (created["id"],)), 1)
        audit = self.connection.execute(
            """SELECT reason,actor_id,old_data,new_data FROM vinto_audit.audit_event
               WHERE entity_table='work_order_line' AND entity_key->>'id'=%s AND action='UPDATE'
               ORDER BY occurred_at DESC LIMIT 1""", (original["id"],)).fetchone()
        self.assertIsNotNone(audit)
        self.assertEqual(audit[0], "work order edit draft line: Corrección de programación QA")
        self.assertEqual(audit[1], self.users["JEFATURA"][0].user_id)
        self.assertEqual(audit[2]["pv_reference"], "PV-001")
        self.assertEqual(audit[3]["pv_reference"], "PV-CORREGIDO")
        self.assertEqual(audit[2]["machine_id"], audit[3]["machine_id"])

        stale = await call("POST", url, json_body={"expected": expected, "replacement": replacement,
                                                  "reason": "Segundo intento con valores anteriores"},
                           cookie=await self.cookie("JEFATURA"))
        self.assertEqual((stale.status, stale.json()["code"]), (409, "WORK_ORDER_DRAFT_CHANGED"))
        current = (await call("GET", f"/api/work-orders/{created['id']}", cookie=await self.cookie("JEFATURA"))).json()
        self.assertEqual(current["baseline"]["lines"][0], item)

    async def test_published_line_edit_is_rejected_without_side_effects(self):
        created = (await self.create()).json()
        existing = created["baseline"]["lines"][0]
        expected = line_body(code=existing["article"]["code"], pv=existing["pv_reference"],
                             quantity=existing["quantity"], due=existing["due_date"])
        body = {"expected": expected, "replacement": {**expected, "quantity": 200},
                "reason": "Incremento posterior a publicación QA"}
        url = f"/api/work-orders/{created['id']}/lines/L1/edit-draft"
        await call("POST", f"/api/work-orders/{created['id']}/publish", cookie=await self.cookie("JEFATURA"))
        reply = await call("POST", url, json_body=body, cookie=await self.cookie("JEFATURA"))
        self.assertEqual((reply.status, reply.json()["code"]), (409, "WORK_ORDER_NOT_DRAFT"))
        detail = (await call("GET", f"/api/work-orders/{created['id']}", cookie=await self.cookie("JEFATURA"))).json()
        self.assertEqual(detail["baseline"]["lines"][0], existing)

    async def test_permissions_machine_restriction_and_invalid_product(self):
        created = (await self.create()).json()
        line = created["baseline"]["lines"][0]
        expected = line_body(code=line["article"]["code"], pv=line["pv_reference"],
                             quantity=line["quantity"], due=line["due_date"])
        body = {"expected": expected, "replacement": {**expected, "quantity": 120},
                "reason": "Corrección operativa de cantidades QA"}
        url = f"/api/work-orders/{created['id']}/lines/L1/edit-draft"
        for profile in ("SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            reply = await call("POST", url, json_body=body, cookie=await self.cookie(profile))
            self.assertEqual(reply.status, 403, profile)
        self.assertEqual((await call("POST", url, json_body=body)).status, 401)
        bad = [
            {**body, "replacement": {**body["replacement"], "machine_code": "MP3"}},
            {**body, "replacement": {**body["replacement"], "quantity": 0}},
            {**body, "reason": "corto"},
        ]
        for payload in bad:
            self.assertEqual((await call("POST", url, json_body=payload,
                                         cookie=await self.cookie("JEFATURA"))).status, 422)
        wrong_machine = {**body, "replacement": {**body["replacement"], "article_code": MP3_CODES[0]}}
        reply = await call("POST", url, json_body=wrong_machine, cookie=await self.cookie("JEFATURA"))
        self.assertEqual((reply.status, reply.json()["code"]), (422, "ARTICLE_NOT_ALLOWED_FOR_MACHINE"))
        missing = {**body, "replacement": {**body["replacement"], "article_code": "NO-EXISTE"}}
        reply = await call("POST", url, json_body=missing, cookie=await self.cookie("JEFATURA"))
        self.assertEqual((reply.status, reply.json()["code"]), (404, "ARTICLE_NOT_FOUND"))
        detail = (await call("GET", f"/api/work-orders/{created['id']}", cookie=await self.cookie("JEFATURA"))).json()
        self.assertEqual(detail["baseline"]["lines"][0], line)

class PublishedRevisionTests(WorkOrderApiCase):
    """E2-B: append-only programming versions; no already-operational OT touched."""

    def revision_body(self, order, *, quantity=150, pv="PV-REPROGRAMADO", article=None,
                      expected_version=None, expected=None):
        line = (order.get("programming") or order["baseline"])["lines"][0]
        old = expected or {
            "pv_reference": line["pv_reference"],
            "article_code": line["article"]["code"],
            "quantity": line["quantity"],
            "due_date": line["due_date"],
        }
        return {"expected_version": expected_version or (order.get("programming") or order["baseline"])["version_number"],
                "expected": old,
                "replacement": {**old, "pv_reference": pv, "quantity": quantity,
                                "article_code": article or old["article_code"], "due_date": "2026-12-20"},
                "reason": "Cambio de programación registrado por Jefatura"}

    async def published(self):
        created = (await self.create()).json()
        result = await call("POST", f"/api/work-orders/{created['id']}/publish",
                            cookie=await self.cookie("JEFATURA"))
        self.assertEqual(result.status, 200)
        return result.json()

    async def test_publish_then_revise_twice_keeps_original_and_displays_current_program(self):
        order = await self.published()
        old_line = order["baseline"]["lines"][0]
        url = f"/api/work-orders/{order['id']}/lines/L1/reprogram"
        first = await call("POST", url, json_body=self.revision_body(order), cookie=await self.cookie("JEFATURA"))
        self.assertEqual(first.status, 200, first.text)
        edited = first.json()
        self.assertEqual((edited["programming"]["version_number"], edited["programming"]["lines"][0]["quantity"]), (2, 150))
        self.assertEqual(edited["baseline"]["lines"][0], old_line, "baseline must be byte-for-byte immutable")
        self.assertEqual(edited["programming"]["lines"][0]["machine"], old_line["machine"])

        second = await call("POST", url, json_body=self.revision_body(edited, quantity=170, pv="PV-TERCERA"),
                            cookie=await self.cookie("JEFATURA"))
        self.assertEqual(second.status, 200, second.text)
        revised = second.json()
        self.assertEqual(revised["programming"]["version_number"], 3)
        self.assertEqual(revised["programming"]["lines"][0]["quantity"], 170)
        self.assertEqual(revised["baseline"]["lines"][0], old_line)
        rows = self.connection.execute(
            """SELECT version_number,kind,published_at IS NOT NULL,reprogram_reason IS NOT NULL
               FROM vinto_txn.work_order_version WHERE work_order_id=%s ORDER BY version_number""",
            (order["id"],)).fetchall()
        self.assertEqual(rows, [(1, "baseline", True, False),
                                (2, "operational", True, True),
                                (3, "operational", True, True)])

        events = await call("GET", f"/api/work-orders/{order['id']}/revisions",
                            cookie=await self.cookie("JEFATURA"))
        self.assertEqual(events.status, 200, events.text)
        history = events.json()
        self.assertEqual([(v["version_number"], v["previous_version"]) for v in history], [(3, 2), (2, 1)])
        self.assertEqual((history[0]["before"]["quantity"], history[0]["after"]["quantity"]), (150, 170))
        self.assertEqual((history[1]["before"]["quantity"], history[1]["after"]["quantity"]), (100, 150))
        self.assertEqual(history[0]["changed_by_id"], str(self.users["JEFATURA"][0].user_id))
        self.assertEqual(history[0]["reason"], "Cambio de programación registrado por Jefatura")
        self.assertTrue(history[0]["changed_at"])
        for version in (2, 3):
            version_id = self.scalar("SELECT id FROM vinto_txn.work_order_version WHERE work_order_id=%s AND version_number=%s", (order["id"], version))
            with self.assertRaises(Exception):
                self.connection.execute("UPDATE vinto_txn.work_order_line SET quantity=1 WHERE work_order_version_id=%s", (version_id,))
        detail = (await call("GET", f"/api/work-orders/{order['id']}", cookie=await self.cookie("JEFATURA"))).json()
        self.assertEqual(detail["programming"]["version_number"], 3)

    async def test_rejects_stale_versions_permissions_invalid_machine_and_invalid_data(self):
        order = await self.published()
        url = f"/api/work-orders/{order['id']}/lines/L1/reprogram"
        body = self.revision_body(order)
        for profile in ("SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            response = await call("POST", url, json_body=body, cookie=await self.cookie(profile))
            self.assertEqual(response.status, 403, profile)
        self.assertEqual((await call("POST", url, json_body=body)).status, 401)
        for extra in [{"machine_code": "MP3"}, {"id": str(uuid4())}]:
            bad = {**body, "replacement": {**body["replacement"], **extra}}
            self.assertEqual((await call("POST", url, json_body=bad,
                             cookie=await self.cookie("JEFATURA"))).status, 422)
        bad_product = {**body, "replacement": {**body["replacement"], "article_code": MP3_CODES[0]}}
        res = await call("POST", url, json_body=bad_product, cookie=await self.cookie("JEFATURA"))
        self.assertEqual((res.status, res.json()["code"]), (422, "ARTICLE_NOT_ALLOWED_FOR_MACHINE"))
        res = await call("POST", url, json_body={**body, "expected_version": 999},
                         cookie=await self.cookie("JEFATURA"))
        self.assertEqual((res.status, res.json()["code"]), (409, "WORK_ORDER_REPROGRAM_CONFLICT"))
        good = await call("POST", url, json_body=body, cookie=await self.cookie("JEFATURA"))
        self.assertEqual(good.status, 200, good.text)
        stale = await call("POST", url, json_body=body, cookie=await self.cookie("JEFATURA"))
        self.assertEqual((stale.status, stale.json()["code"]), (409, "WORK_ORDER_REPROGRAM_CONFLICT"))
        self.assertEqual((await call("GET", f"/api/work-orders/{order['id']}/revisions",
                                    cookie=await self.cookie("SUPERVISION"))).status, 403)

    async def test_valid_product_correction_and_quantity_decrease_before_any_production(self):
        order = await self.published()
        original = order["baseline"]["lines"][0]
        url = f"/api/work-orders/{order['id']}/lines/L1/reprogram"
        corrected = await call("POST", url,
                               json_body=self.revision_body(order, article=MP1_CODES[1], quantity=120),
                               cookie=await self.cookie("JEFATURA"))
        self.assertEqual(corrected.status, 200, corrected.text)
        second = corrected.json()
        self.assertEqual(second["programming"]["lines"][0]["article"]["code"], MP1_CODES[1])
        self.assertEqual(second["baseline"]["lines"][0]["article"]["code"], original["article"]["code"])
        reduced = await call("POST", url,
                             json_body=self.revision_body(second, quantity=80, pv="PV-REDUCCION"),
                             cookie=await self.cookie("JEFATURA"))
        self.assertEqual(reduced.status, 200, reduced.text)
        updated = reduced.json()
        self.assertEqual(updated["programming"]["version_number"], 3)
        self.assertEqual(updated["programming"]["lines"][0]["quantity"], 80)
        self.assertEqual(updated["programming"]["lines"][0]["machine"], original["machine"])
        self.assertEqual(updated["baseline"]["lines"][0], original)
        history = (await call("GET", f"/api/work-orders/{order['id']}/revisions",
                              cookie=await self.cookie("JEFATURA"))).json()
        self.assertEqual(history[0]["before"]["quantity"], 120)
        self.assertEqual(history[0]["after"]["quantity"], 80)
        self.assertEqual(history[1]["before"]["article_code"], original["article"]["code"])
        self.assertEqual(history[1]["after"]["article_code"], MP1_CODES[1])

    async def test_any_execution_history_blocks_revision_before_writing(self):
        order = await self.published()
        baseline_line = order["baseline"]["lines"][0]
        machine_id = self.scalar("SELECT machine_id FROM vinto_txn.work_order_line WHERE id=%s", (baseline_line["id"],))
        self.connection.execute(
            """INSERT INTO vinto_txn.work_order_line_execution
                (baseline_line_id, work_order_id, machine_id)
                VALUES (%s,%s,%s)""", (baseline_line["id"], order["id"], machine_id))
        url = f"/api/work-orders/{order['id']}/lines/L1/reprogram"
        resp = await call("POST", url, json_body=self.revision_body(order), cookie=await self.cookie("JEFATURA"))
        self.assertEqual((resp.status, resp.json()["code"]), (409, "WORK_ORDER_REPROGRAM_BLOCKED"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s", (order["id"],)), 1)


class PermissionTests(WorkOrderApiCase):
    async def test_without_a_session_every_endpoint_is_401(self):
        order = (await self.create()).json()
        requests = [("POST", "/api/work-orders", payload()), ("GET", "/api/work-orders", None), ("GET", f"/api/work-orders/{order['id']}", None),
                    ("POST", f"/api/work-orders/{order['id']}/lines", line_body()), ("POST", f"/api/work-orders/{order['id']}/publish", None)]
        for method, path, body in requests:
            for cookie in (None, secrets.token_urlsafe(32)):
                with self.subTest(method=method, path=path.split("/")[-1]):
                    reply = await call(method, path, json_body=body, cookie=cookie)
                    self.assertEqual((reply.status, reply.json()), (401, {"detail": "No autenticado"}))

    async def test_every_profile_can_read_and_only_jefatura_can_write(self):
        order = (await self.create()).json()
        for profile in PROFILES:
            cookie = await self.cookie(profile)
            with self.subTest(profile=profile):
                self.assertEqual((await call("GET", "/api/work-orders", cookie=cookie)).status, 200)
                self.assertEqual((await call("GET", f"/api/work-orders/{order['id']}", cookie=cookie)).status, 200)
                writes = [await call("POST", "/api/work-orders", json_body=payload(), cookie=cookie),
                          await call("POST", f"/api/work-orders/{order['id']}/lines", json_body=line_body(), cookie=cookie),
                          await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=cookie)]
                expected = 201 if profile == "JEFATURA" else 403
                self.assertEqual([w.status for w in writes][:2], [expected, expected] if profile == "JEFATURA" else [403, 403])
                if profile != "JEFATURA":
                    self.assertEqual(writes[2].status, 403)
                    self.assertEqual(writes[0].json(), {"detail": "Permiso insuficiente"})

    async def test_forbidden_writes_leave_no_trace(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.work_order")
        for profile in ("SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            reply = await self.create(profile)
            self.assertEqual(reply.status, 403, profile)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), before)

    async def test_supervision_cannot_modify_a_published_baseline_or_publish_a_draft(self):
        draft = (await self.create()).json()
        cookie = await self.cookie("SUPERVISION")
        self.assertEqual((await call("POST", f"/api/work-orders/{draft['id']}/publish", cookie=cookie)).status, 403)
        status = (await call("GET", f"/api/work-orders/{draft['id']}", cookie=cookie)).json()["status"]
        self.assertEqual(status, "draft")


class ValidationAndErrorTests(WorkOrderApiCase):
    async def test_invalid_payloads_are_422_and_create_nothing(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.work_order")
        bad = [
            {"machine_code": "MP1"}, {"machine_code": "MP1", "lines": []}, {"lines": payload()["lines"]},
            payload(lines=[{**line_body(), "quantity": 0}]), payload(lines=[{**line_body(), "quantity": -3}]),
            payload(lines=[{**line_body(), "pv_reference": ""}]), payload(lines=[{**line_body(), "due_date": "2026-13-45"}]),
            payload(lines=[{**line_body(), "quantity": "abc"}]), payload(lines=[{**line_body(), "quantity": 1.2345}]),
            payload(lines=[{**line_body(), "unit": "KG"}]),  # the client cannot send the unit
            payload(lines=[{**line_body(), "description": "x"}]), payload(lines=[{**line_body(), "article_version_id": str(uuid4())}]),
            {**payload(), "number": "OT-2026-9999"},  # the client cannot choose the number
        ]
        for body in bad:
            with self.subTest(body=json.dumps(body)[:70]):
                self.assertEqual((await self.create(body=body)).status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), before)

    async def test_domain_errors_map_to_404_and_422_without_sql_details(self):
        cases = [
            (payload("NOPE"), 404, "MACHINE_NOT_FOUND"),
            (payload(lines=[{**line_body(), "article_code": "NO-EXISTE-001"}]), 404, "ARTICLE_NOT_FOUND"),
            (payload(lines=[{**line_body(), "article_code": MP3_CODES[0]}]), 422, "ARTICLE_NOT_ALLOWED_FOR_MACHINE"),
        ]
        for body, status, code in cases:
            reply = await self.create(body=body)
            self.assertEqual((reply.status, reply.json()["code"]), (status, code))
            for forbidden in ("SELECT", "psycopg", "vinto_txn", "Traceback", "constraint"):
                self.assertNotIn(forbidden, reply.text)

    async def test_machine_outside_bobinas_is_422(self):
        sector_id = self.scalar("INSERT INTO vinto_master.sector (code,name) VALUES ('OTRO','Otro') ON CONFLICT (code) DO UPDATE SET name='Otro' RETURNING id")
        self.connection.execute("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'OTRO1','Otra') ON CONFLICT (code) DO NOTHING", (sector_id,))
        reply = await self.create(body=payload("OTRO1"))
        self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))

    async def test_a_failing_second_line_rolls_the_whole_request_back(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.work_order")
        body = payload(lines=[{"pv_reference": "PV-OK", "article_code": MP1_CODES[0], "quantity": 1, "due_date": "2026-10-30"},
                              {"pv_reference": "PV-BAD", "article_code": MP3_CODES[0], "quantity": 1, "due_date": "2026-10-30"}])
        reply = await self.create(body=body)
        self.assertEqual(reply.status, 422)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), before)

    async def test_unknown_and_malformed_ids_are_a_generic_404(self):
        cookie = await self.cookie("JEFATURA")
        for path in (f"/api/work-orders/{uuid4()}", "/api/work-orders/not-a-uuid", "/api/work-orders/123"):
            reply = await call("GET", path, cookie=cookie)
            self.assertEqual((reply.status, reply.json()), (404, {"detail": "Orden de trabajo no encontrada", "code": "WORK_ORDER_NOT_FOUND"}), path)
        for suffix, body in (("lines", line_body()), ("publish", None)):
            reply = await call("POST", f"/api/work-orders/{uuid4()}/{suffix}", json_body=body, cookie=cookie)
            self.assertEqual(reply.status, 404)

    async def test_database_down_is_a_safe_503(self):
        cookie = await self.cookie("JEFATURA")
        closed = SecretStr(make_conninfo(database_url(self.database), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed):
            reply = await call("GET", "/api/work-orders", cookie=cookie)
        self.assertEqual((reply.status, reply.json()), (503, {"status": "error", "database": "unavailable"}))
        self.assertNotIn("postgresql://", reply.text)


class ResponseHygieneTests(WorkOrderApiCase):
    async def test_responses_expose_only_the_public_model(self):
        order = (await self.create()).json()
        published = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=await self.cookie("JEFATURA"))).json()
        listing = (await call("GET", "/api/work-orders", cookie=await self.cookie("CALIDAD"))).json()
        for model in (order, published, listing[0]):
            self.assertEqual(sorted(model), ["baseline", "id", "machine", "number", "programming", "status"])
            self.assertIsNone(model["programming"], "unrevised OTs retain the original public baseline model")
            self.assertEqual(sorted(model["baseline"]), ["id", "lines", "published_at", "version_number"])
            self.assertEqual(sorted(model["machine"]), ["code", "name"])
            for item in model["baseline"]["lines"]:
                self.assertEqual(sorted(item), ["article", "due_date", "id", "line_code", "machine", "pv_reference", "quantity", "unit"])
                self.assertEqual(sorted(item["article"]), ["code", "description"])
        text = json.dumps([order, published, listing]).lower()
        for forbidden in ("created_by", "updated_by", "password", "token", "hash", "cookie", "audit", "version_id", "unit_id"):
            self.assertNotIn(forbidden, text)

    async def test_request_id_is_server_generated_and_the_actor_is_the_session_user(self):
        reply = await call("POST", "/api/work-orders", json_body=payload(), cookie=await self.cookie("JEFATURA"), extra_headers=[("x-request-id", "client-chosen")])
        order_id = reply.json()["id"]
        actor, _ = self.users["JEFATURA"]
        row = self.connection.execute(
            "SELECT request_id,actor_id,reason FROM vinto_audit.audit_event WHERE entity_table='work_order' AND entity_key->>'id'=%s", (order_id,)).fetchone()
        self.assertNotEqual(row[0], "client-chosen")
        UUID(row[0].split(":", 1)[1] if ":" in row[0] else row[0])
        self.assertEqual((row[1], row[2]), (actor.user_id, "work order create"))
        self.assertEqual(self.scalar("SELECT created_by FROM vinto_txn.work_order WHERE id=%s", (order_id,)), actor.user_id)

    async def test_quantity_round_trips_as_a_json_number(self):
        reply = await self.create(body=payload(lines=[{"pv_reference": "PV-Q", "article_code": MP1_CODES[0], "quantity": 12.5, "due_date": "2026-10-30"}]))
        quantity = reply.json()["baseline"]["lines"][0]["quantity"]
        self.assertIsInstance(quantity, (int, float))
        self.assertEqual(quantity, 12.5)
        self.assertEqual(date.fromisoformat(reply.json()["baseline"]["lines"][0]["due_date"]), date(2026, 10, 30))



class ArchiveApiTests(WorkOrderApiCase):
    async def test_jefatura_archive_and_restore_preserves_history_and_authz(self):
        order = (await self.create()).json()
        oid = order["id"]
        jef = await self.cookie("JEFATURA")
        op = await self.cookie("OPERACION")
        supervision = await self.cookie("SUPERVISION")

        for cookie in (op, supervision):
            result = await call("POST", f"/api/work-orders/{oid}/archive",
                                json_body={"reason": "Datos ficticios de ejemplo"}, cookie=cookie)
            self.assertEqual(result.status, 403)
        self.assertEqual((await call("GET", "/api/work-orders?archived=true", cookie=op)).status, 403)
        self.assertEqual((await call("GET", f"/api/work-orders/{oid}?include_archived=true", cookie=op)).status, 403)
        self.assertEqual((await call("POST", f"/api/work-orders/{oid}/archive",
                                     json_body={"reason": "muy corta"}, cookie=jef)).status, 422)

        done = await call("POST", f"/api/work-orders/{oid}/archive",
                          json_body={"reason": "Datos ficticios de ejemplo"}, cookie=jef)
        self.assertEqual(done.status, 200)
        self.assertEqual(done.json(), order)  # shape backwards-compatible
        self.assertNotIn(oid, [x["id"] for x in (await call("GET", "/api/work-orders", cookie=jef)).json()])
        self.assertEqual((await call("GET", f"/api/work-orders/{oid}", cookie=jef)).status, 404)
        historical = await call("GET", "/api/work-orders?archived=true", cookie=supervision)
        self.assertEqual(historical.status, 200)
        self.assertIn(oid, [x["id"] for x in historical.json()])
        self.assertEqual((await call("GET", f"/api/work-orders/{oid}?include_archived=true",
                                     cookie=supervision)).status, 200)
        self.assertEqual((await call("POST", f"/api/work-orders/{oid}/lines",
                                     json_body=line_body(), cookie=jef)).status, 404)
        self.assertEqual((await call("POST", f"/api/work-orders/{oid}/publish",
                                     cookie=jef)).status, 404)
        self.assertEqual((await call("POST", f"/api/work-orders/{oid}/restore",
                                     cookie=supervision)).status, 403)
        restored = await call("POST", f"/api/work-orders/{oid}/restore", cookie=jef)
        self.assertEqual(restored.status, 200)
        self.assertEqual(restored.json(), order)
        self.assertIn(oid, [x["id"] for x in (await call("GET", "/api/work-orders", cookie=jef)).json()])
        self.assertEqual((await call("POST", f"/api/work-orders/{oid}/restore",
                                     cookie=jef)).json()["code"], "WORK_ORDER_NOT_ARCHIVED")

    async def test_cannot_archive_in_progress_or_archived_twice(self):
        order = (await self.create()).json()
        oid = order["id"]
        jef = await self.cookie("JEFATURA")
        await call("POST", f"/api/work-orders/{oid}/publish", cookie=jef)
        self.connection.execute("UPDATE vinto_txn.work_order SET status='in_progress' WHERE id=%s", (UUID(oid),))
        blocked = await call("POST", f"/api/work-orders/{oid}/archive",
                             json_body={"reason": "Test con historial activo"}, cookie=jef)
        self.assertEqual((blocked.status, blocked.json()["code"]), (409, "WORK_ORDER_ARCHIVE_BLOCKED"))
        draft = (await self.create()).json()
        did = draft["id"]
        self.assertEqual((await call("POST", f"/api/work-orders/{did}/archive",
                                      json_body={"reason": "Escenario de ejemplo seguro"},
                                      cookie=jef)).status, 200)
        self.assertEqual((await call("POST", f"/api/work-orders/{did}/archive",
                                      json_body={"reason": "Escenario de ejemplo seguro"},
                                      cookie=jef)).status, 404)


if __name__ == "__main__":
    unittest.main()
