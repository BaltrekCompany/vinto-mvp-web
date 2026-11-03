"""MF13-03.B PR2: HTTP contract of multi-machine work orders (machine per line, server gate, information isolation).

Reuses the ASGI caller of test_work_orders_api. Ephemeral *_test database; the gate is enabled only through patch.object on the server settings.
"""

import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from psycopg.conninfo import make_conninfo  # noqa: F401  (kept for parity with the sibling module)
from pydantic import SecretStr

from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, database_url, drop_database

try:
    from test_work_orders_api import MP1_CODES, MP3_CODES, call
except ModuleNotFoundError:
    from tests.test_work_orders_api import MP1_CODES, MP3_CODES, call

STATE = {}
MP3_ONLY = [c for c in MP3_CODES if c not in MP1_CODES]
MP1_ONLY = [c for c in MP1_CODES if c not in MP3_CODES]
RB1_ARTICLE = MP1_ONLY[1]
USERS = {  # name -> (profile, sectors)
    "JEFATURA": ("JEFATURA", ("BOBINAS", "REBOBINADO")),
    "JEFATURA_BOBINAS": ("JEFATURA", ("BOBINAS",)),
    "SUPERVISION": ("SUPERVISION", ("BOBINAS", "REBOBINADO")),
    "OPERACION": ("OPERACION", ("BOBINAS", "REBOBINADO")),
    "CALIDAD": ("CALIDAD", ("BOBINAS", "REBOBINADO")),
    "DATA_BALTREK": ("DATA_BALTREK", ("BOBINAS", "REBOBINADO")),
}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_wmapi_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


def body_line(code, machine=None, pv="PV-1"):
    body = {"pv_reference": pv, "article_code": code, "quantity": 10, "due_date": "2026-10-30"}
    if machine is not None:
        body["machine_code"] = machine
    return body


def order_body(lines, machine="MP1"):
    return {"machine_code": machine, "lines": lines}


THREE = [body_line(MP1_CODES[0], "MP1", "PV-1"), body_line(MP1_CODES[1], "MP1", "PV-2"), body_line(MP3_ONLY[0], "MP3", "PV-3")]


class MultiMachineApiCase(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.database = copy_database(STATE["template"], "vinto_wmapi")
        cls.connection = connect(cls.database)
        cls.patcher = patch.object(settings, "database_url", SecretStr(database_url(cls.database)))
        cls.patcher.start()
        cls.connection.execute("SELECT set_config('vinto.reason','mf13-03b fixture',false)")
        sector = cls.connection.execute("SELECT id FROM vinto_master.sector WHERE code='REBOBINADO'").fetchone()[0]
        cls.connection.execute("INSERT INTO vinto_master.machine (sector_id,code,name) VALUES (%s,'RB1','RB1')", (sector,))
        cls.connection.execute("""INSERT INTO vinto_master.article_machine (article_id,machine_id)
                                  SELECT a.id,m.id FROM vinto_master.article a, vinto_master.machine m WHERE a.code=%s AND m.code='RB1'""", (RB1_ARTICLE,))
        cls.users, cls.cookies = {}, {}
        for name, (profile, sectors) in USERS.items():
            password = "pw-" + secrets.token_urlsafe(18)
            created = create_user(cls.connection, username=f"wmapi.{name.lower()}", display_name=name.title(), profile_code=profile, password=password, sectors=sectors)
            cls.users[name] = (created, password)

    @classmethod
    def tearDownClass(cls):
        cls.patcher.stop()
        cls.connection.close()
        drop_database(cls.database)

    async def cookie(self, name):
        if name not in self.cookies:
            created, password = self.users[name]
            reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
            self.assertEqual(reply.status, 200, name)
            self.cookies[name] = reply.set_cookie_value()
        return self.cookies[name]

    async def post(self, path, body=None, user="JEFATURA"):
        return await call("POST", path, json_body=body, cookie=await self.cookie(user))

    async def get(self, path, user="JEFATURA"):
        return await call("GET", path, cookie=await self.cookie(user))

    def gate(self, value=True):
        patcher = patch.object(settings, "work_orders_multi_machine_enabled", value)
        patcher.start()
        self.addCleanup(patcher.stop)

    def scalar(self, query, params=()):
        return self.connection.execute(query, params).fetchone()[0]


class ContractTests(MultiMachineApiCase):
    async def test_legacy_request_without_machine_per_line_is_unchanged_and_reports_the_line_machine(self):
        reply = await self.post("/api/work-orders", order_body([body_line(MP1_CODES[0])]))
        self.assertEqual(reply.status, 201)
        order = reply.json()
        self.assertEqual(order["machine"], {"code": "MP1", "name": "MP1"})
        self.assertEqual(order["baseline"]["lines"][0]["machine"], {"code": "MP1", "name": "MP1"})

    async def test_three_lines_mp1_mp1_mp3_with_the_gate_enabled(self):
        self.gate()
        reply = await self.post("/api/work-orders", order_body(THREE))
        self.assertEqual(reply.status, 201)
        order = reply.json()
        self.assertEqual(order["machine"]["code"], "MP1")
        self.assertEqual([(l["line_code"], l["machine"]["code"]) for l in order["baseline"]["lines"]], [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        published = await self.post(f"/api/work-orders/{order['id']}/publish")
        self.assertEqual(published.status, 200)
        again = await self.post(f"/api/work-orders/{order['id']}/publish")
        self.assertEqual(again.json(), published.json())
        detail = await self.get(f"/api/work-orders/{order['id']}")
        self.assertEqual(detail.json(), published.json())
        listed = await self.get("/api/work-orders?machine_code=MP3")
        self.assertIn(order["id"], [o["id"] for o in listed.json()])

    async def test_add_line_with_machine_to_a_draft(self):
        self.gate()
        order = (await self.post("/api/work-orders", order_body([body_line(MP1_CODES[0])]))).json()
        reply = await self.post(f"/api/work-orders/{order['id']}/lines", body_line(MP3_ONLY[0], "MP3", "PV-2"))
        self.assertEqual(reply.status, 201)
        self.assertEqual([l["machine"]["code"] for l in reply.json()["baseline"]["lines"]], ["MP1", "MP3"])
        await self.post(f"/api/work-orders/{order['id']}/publish")
        late = await self.post(f"/api/work-orders/{order['id']}/lines", body_line(MP3_ONLY[0], "MP3", "PV-3"))
        self.assertEqual((late.status, late.json()["code"]), (409, "WORK_ORDER_ALREADY_PUBLISHED"))

    async def test_the_client_cannot_send_internal_ids_or_versions(self):
        for extra in ({"machine_id": str(uuid4())}, {"work_order_version_id": str(uuid4())}, {"operational_version_id": str(uuid4())}):
            reply = await self.post("/api/work-orders", order_body([{**body_line(MP1_CODES[0]), **extra}]))
            self.assertEqual(reply.status, 422, extra)
        order = (await self.post("/api/work-orders", order_body([body_line(MP1_CODES[0])]))).json()
        reply = await self.post(f"/api/work-orders/{order['id']}/lines", {**body_line(MP1_CODES[1]), "machine_id": str(uuid4())})
        self.assertEqual(reply.status, 422)

    async def test_invalid_machine_code_shapes_are_rejected(self):
        for bad in ("", "x" * 65, 3):
            reply = await self.post("/api/work-orders", order_body([{**body_line(MP1_CODES[0]), "machine_code": bad}]))
            self.assertEqual(reply.status, 422, bad)
        reply = await self.post("/api/work-orders", order_body([body_line(MP1_CODES[0], "NOPE")]))
        self.assertEqual((reply.status, reply.json()["code"]), (404, "MACHINE_NOT_FOUND"))


class GateTests(MultiMachineApiCase):
    async def test_multi_machine_is_rejected_by_default_with_nothing_written(self):
        before = self.scalar("SELECT count(*) FROM vinto_txn.work_order")
        reply = await self.post("/api/work-orders", order_body(THREE))
        self.assertEqual((reply.status, reply.json()["code"]), (422, "MULTI_MACHINE_DISABLED"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order"), before)

    async def test_the_client_cannot_turn_the_gate_on(self):
        for path, headers in (("/api/work-orders?work_orders_multi_machine_enabled=true", ()),
                              ("/api/work-orders", (("X-Work-Orders-Multi-Machine-Enabled", "true"),))):
            reply = await call("POST", path, json_body=order_body(THREE), cookie=await self.cookie("JEFATURA"), extra_headers=headers)
            self.assertEqual((reply.status, reply.json()["code"]), (422, "MULTI_MACHINE_DISABLED"), path)
        body = {**order_body(THREE), "work_orders_multi_machine_enabled": True}
        self.assertEqual((await self.post("/api/work-orders", body)).status, 422)

    async def test_failure_of_one_line_creates_nothing_over_http(self):
        self.gate()
        before = self.scalar("SELECT count(*) FROM vinto_txn.work_order_line")
        lines = THREE + [body_line(MP1_ONLY[0], "MP3", "PV-4")]  # not allowed on MP3
        reply = await self.post("/api/work-orders", order_body(lines))
        self.assertEqual((reply.status, reply.json()["code"]), (422, "ARTICLE_NOT_ALLOWED_FOR_MACHINE"))
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.work_order_line"), before)

    async def test_permissions_are_unchanged(self):
        self.gate()
        for user in ("SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            self.assertEqual((await self.post("/api/work-orders", order_body(THREE), user)).status, 403, user)


class IsolationTests(MultiMachineApiCase):
    async def asyncSetUp(self):
        self.gate()
        self.cross = (await self.post("/api/work-orders", order_body([body_line(MP1_CODES[0], "MP1"), body_line(RB1_ARTICLE, "RB1", "PV-2")]))).json()
        self.same_sector = (await self.post("/api/work-orders", order_body(THREE))).json()
        for order in (self.cross, self.same_sector):
            await self.post(f"/api/work-orders/{order['id']}/publish")
        self.single = (await self.post("/api/work-orders", order_body([body_line(MP1_CODES[1], pv="PV-S")]))).json()
        await self.post(f"/api/work-orders/{self.single['id']}/publish")

    async def ids(self, user):
        reply = await self.get("/api/work-orders?limit=500", user)
        self.assertEqual(reply.status, 200, user)
        return {o["id"] for o in reply.json()}

    async def test_managers_with_full_scope_see_the_complete_orders(self):
        for user in ("JEFATURA", "SUPERVISION"):
            self.assertTrue({self.cross["id"], self.same_sector["id"], self.single["id"]} <= await self.ids(user), user)
            detail = await self.get(f"/api/work-orders/{self.cross['id']}", user)
            self.assertEqual([l["machine"]["code"] for l in detail.json()["baseline"]["lines"]], ["MP1", "RB1"], user)

    async def test_operation_quality_and_data_never_see_multi_machine_orders(self):
        for user in ("OPERACION", "CALIDAD", "DATA_BALTREK"):
            ids = await self.ids(user)
            self.assertNotIn(self.single["id"], ids, user)  # PR5: con la compuerta encendida el filtro por máquina está activo y estos usuarios no tienen concesiones
            self.assertFalse({self.cross["id"], self.same_sector["id"]} & ids, user)
            for hidden in (self.cross, self.same_sector):
                reply = await self.get(f"/api/work-orders/{hidden['id']}", user)
                self.assertEqual((reply.status, reply.json()["code"]), (404, "WORK_ORDER_NOT_FOUND"), (user, hidden["id"]))
            listed = await self.get("/api/work-orders?machine_code=MP3&limit=500", user)
            self.assertEqual(listed.json(), [], user)
            self.assertNotIn("RB1", (await self.get("/api/work-orders?limit=500", user)).text)

    async def test_a_manager_with_a_partial_scope_gets_no_part_of_a_cross_sector_order(self):
        self.assertNotIn(self.cross["id"], await self.ids("JEFATURA_BOBINAS"))
        self.assertIn(self.same_sector["id"], await self.ids("JEFATURA_BOBINAS"))
        reply = await self.get(f"/api/work-orders/{self.cross['id']}", "JEFATURA_BOBINAS")
        self.assertEqual(reply.status, 404)
        self.assertNotIn("RB1", reply.text)
        self.assertNotIn("RB1", (await self.get("/api/work-orders?limit=500", "JEFATURA_BOBINAS")).text)
        for path in (f"/api/work-orders/{self.cross['id']}/publish", f"/api/work-orders/{self.cross['id']}/lines"):
            body = None if path.endswith("publish") else body_line(MP1_CODES[0])
            self.assertEqual((await self.post(path, body, "JEFATURA_BOBINAS")).status, 404, path)


if __name__ == "__main__":
    unittest.main()
