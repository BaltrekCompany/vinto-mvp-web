"""MF13-03.B PR4: HTTP contract of POST /api/work-orders/{id}/activate-all (preview + confirm).

Shares the ASGI scaffolding of test_assignments_api. The gate is a server setting patched in the test process; the client can never set it.
"""

import unittest
from unittest.mock import patch
from uuid import uuid4

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders import service as _work_orders
from app.work_orders.service import LineInput

try:
    import test_assignments_api as base
except ModuleNotFoundError:
    from tests import test_assignments_api as base

try:
    from scope_helpers import internal
except ModuleNotFoundError:
    from tests.scope_helpers import internal

call = base.call
MP1_CODES, MP3_CODES = base.MP1_CODES, base.MP3_CODES
MP3_ONLY = [c for c in MP3_CODES if c not in MP1_CODES]
MP1_ONLY = [c for c in MP1_CODES if c not in MP3_CODES]


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_aaapi_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])


def three_line_body():
    return {"machine_code": "MP1", "lines": [
        {"pv_reference": "PV-1", "article_code": MP1_CODES[0], "quantity": 10, "due_date": "2026-11-01", "machine_code": "MP1"},
        {"pv_reference": "PV-2", "article_code": MP1_CODES[1], "quantity": 10, "due_date": "2026-11-01", "machine_code": "MP1"},
        {"pv_reference": "PV-3", "article_code": MP3_ONLY[0], "quantity": 10, "due_date": "2026-11-01", "machine_code": "MP3"}]}


class ActivateAllApiTests(base.AssignmentApiCase):
    def gate(self, value=True):
        patcher = patch.object(settings, "work_orders_multi_machine_enabled", value)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def mixed_order(self):
        self.gate(True)
        jefatura = await self.cookie("JEFATURA")
        created = await call("POST", "/api/work-orders", json_body=three_line_body(), cookie=jefatura)
        self.assertEqual(created.status, 201, created.text)
        published = await call("POST", f"/api/work-orders/{created.json()['id']}/publish", cookie=jefatura)
        self.assertEqual(published.status, 200, published.text)
        return published.json()

    async def post(self, order_id, body, profile="SUPERVISION", path=None):
        return await call("POST", path or f"/api/work-orders/{order_id}/activate-all", json_body=body, cookie=await self.cookie(profile) if profile else None)

    def active_count(self):
        return self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'")

    async def test_preview_then_confirm_activates_the_three_lines_and_a_retry_is_idempotent(self):
        order = await self.mixed_order()
        preview = await self.post(order["id"], {"dry_run": True})
        self.assertEqual(preview.status, 200, preview.text)
        body = preview.json()
        self.assertEqual((body["dry_run"], body["outcome"], body["can_confirm"]), (True, "preview", True))
        self.assertEqual(body["summary"], {"activate": 3, "already_active": 0, "blocked": 0, "expired_to_finish": 0, "conflicts": 0})
        self.assertEqual([(l["line_code"], l["machine"]["code"], l["action"]) for l in body["lines"]], [("L1", "MP1", "activate"), ("L2", "MP1", "activate"), ("L3", "MP3", "activate")])
        self.assertEqual(sorted(body["lines"][0]), ["action", "article", "assignment_id", "baseline_line_id", "line_code", "machine", "operating_date", "pv_reference", "reason", "shift"])
        self.assertEqual(self.active_count(), 0)
        confirm = await self.post(order["id"], {"dry_run": False, "plan_hash": body["plan_hash"]})
        self.assertEqual(confirm.status, 201, confirm.text)
        done = confirm.json()
        self.assertEqual((done["outcome"], done["dry_run"], len(done["activated"]), len(done["finished"])), ("applied", False, 3, 0))
        self.assertEqual(sorted(a["machine"]["code"] for a in done["activated"]), ["MP1", "MP1", "MP3"])
        self.assertEqual(self.active_count(), 3)
        retry = await self.post(order["id"], {"dry_run": False, "plan_hash": body["plan_hash"]})
        self.assertEqual(retry.status, 200)
        self.assertEqual((retry.json()["outcome"], len(retry.json()["activated"]), len(retry.json()["already_active"])), ("already_in_effect", 0, 3))
        self.assertEqual(self.active_count(), 3)
        lines = (await call("GET", "/api/assignments/active-lines?machine_code=MP1", cookie=await self.cookie("SUPERVISION"))).json()
        self.assertEqual([i["assignment"]["line"]["line_code"] for i in lines["assignments"]], ["L1", "L2"])

    async def test_the_responses_do_not_expose_internal_identifiers(self):
        order = await self.mixed_order()
        preview = await self.post(order["id"], {"dry_run": True})
        done = await self.post(order["id"], {"dry_run": False, "plan_hash": preview.json()["plan_hash"]})
        text = (preview.text + done.text).lower()
        for forbidden in ("machine_id", "shift_schedule", "article_version", "unit_id", "created_by", "updated_by", "password", "token", "operational_line"):
            self.assertNotIn(forbidden, text)

    async def test_authentication_and_permissions(self):
        order = await self.mixed_order()
        self.assertEqual((await self.post(order["id"], {"dry_run": True}, profile=None)).status, 401)
        for profile in ("JEFATURA", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            self.assertEqual((await self.post(order["id"], {"dry_run": True}, profile=profile)).status, 403, profile)
            self.assertEqual((await self.post(order["id"], {"dry_run": False, "plan_hash": "a" * 64}, profile=profile)).status, 403, profile)
        self.assertEqual(self.active_count(), 0)

    async def test_unknown_or_malformed_order_is_a_404(self):
        self.gate(True)
        for order_id in (str(uuid4()), "not-a-uuid"):
            reply = await self.post(order_id, {"dry_run": True})
            self.assertEqual((reply.status, reply.json()["code"]), (404, "WORK_ORDER_NOT_FOUND"), order_id)

    async def test_strict_request_contract(self):
        order = await self.mixed_order()
        good_hash = "a" * 64
        invalid = ({}, {"plan_hash": good_hash}, {"dry_run": False}, {"dry_run": True, "plan_hash": good_hash}, {"dry_run": False, "plan_hash": "xyz"},
                   {"dry_run": False, "plan_hash": good_hash.upper()}, {"dry_run": "maybe"},
                   {"dry_run": True, "machine_code": "MP3"}, {"dry_run": True, "machine_id": str(uuid4())}, {"dry_run": True, "shift": "NOCHE"},
                   {"dry_run": True, "operating_date": "2026-10-06"}, {"dry_run": True, "operational_version_id": str(uuid4())},
                   {"dry_run": True, "replace_assignment_ids": [str(uuid4())]}, {"dry_run": True, "work_orders_multi_machine_enabled": True})
        for body in invalid:
            self.assertEqual((await self.post(order["id"], body)).status, 422, body)
        self.assertEqual(self.active_count(), 0)

    async def test_the_gate_off_rejects_everything_and_the_client_cannot_turn_it_on(self):
        order = await self.mixed_order()
        self.gate(False)
        for body in ({"dry_run": True}, {"dry_run": False, "plan_hash": "a" * 64}):
            reply = await self.post(order["id"], body)
            self.assertEqual((reply.status, reply.json()["code"]), (422, "MULTI_MACHINE_DISABLED"), body)
        attempts = await call("POST", f"/api/work-orders/{order['id']}/activate-all?work_orders_multi_machine_enabled=true", json_body={"dry_run": True},
                              cookie=await self.cookie("SUPERVISION"), extra_headers=(("x-work-orders-multi-machine-enabled", "true"),))
        self.assertEqual((attempts.status, attempts.json()["code"]), (422, "MULTI_MACHINE_DISABLED"))
        self.assertIs(settings.work_orders_multi_machine_enabled, False)
        self.assertEqual(self.active_count(), 0)

    async def test_a_stale_plan_hash_is_a_409_and_writes_nothing(self):
        order = await self.mixed_order()
        stale = (await self.post(order["id"], {"dry_run": True})).json()["plan_hash"]
        await self.activate(order, 0)  # individual activation changes the state after the approved preview
        reply = await self.post(order["id"], {"dry_run": False, "plan_hash": stale})
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ACTIVATION_PLAN_CHANGED"))
        self.assertEqual(self.active_count(), 1)

    async def test_another_order_on_a_machine_blocks_everything_with_a_409(self):
        order = await self.mixed_order()
        jefatura = await self.cookie("JEFATURA")
        rival = (await call("POST", "/api/work-orders", json_body=base.order_body("MP1", 1), cookie=jefatura)).json()
        rival = (await call("POST", f"/api/work-orders/{rival['id']}/publish", cookie=jefatura)).json()
        self.assertEqual((await self.activate(rival, 0)).status, 201)
        preview = (await self.post(order["id"], {"dry_run": True})).json()
        self.assertEqual((preview["can_confirm"], preview["summary"]["conflicts"], preview["summary"]["blocked"]), (False, 1, 2))
        self.assertEqual(preview["conflicts"][0]["work_order"]["number"], rival["number"])
        reply = await self.post(order["id"], {"dry_run": False, "plan_hash": preview["plan_hash"]})
        self.assertEqual((reply.status, reply.json()["code"]), (409, "ACTIVATION_BLOCKED"))
        self.assertEqual(self.active_count(), 1)  # only the rival's line; nothing finished

    async def test_a_draft_order_is_a_409(self):
        self.gate(True)
        draft = (await call("POST", "/api/work-orders", json_body=base.order_body("MP1", 1), cookie=await self.cookie("JEFATURA"))).json()
        reply = await self.post(draft["id"], {"dry_run": True})
        self.assertEqual((reply.status, reply.json()["code"]), (409, "WORK_ORDER_NOT_ACTIVATABLE"))

    async def test_a_machine_outside_the_supervisors_scope_is_a_404_that_reveals_nothing(self):
        self.gate(True)
        c = self.connection
        c.execute("SELECT set_config('vinto.reason','pr4 api fixture',false)")
        if not self.scalar("SELECT count(*) FROM vinto_master.machine WHERE code='RB1'"):
            c.execute("INSERT INTO vinto_master.machine (sector_id,code,name) SELECT id,'RB1','RB1' FROM vinto_master.sector WHERE code='REBOBINADO'")
            c.execute("INSERT INTO vinto_master.article_machine (article_id,machine_id) SELECT a.id,m.id FROM vinto_master.article a, vinto_master.machine m WHERE a.code=%s AND m.code='RB1'", (MP1_ONLY[1],))
        jefatura = self.users["JEFATURA"][0].user_id
        view = internal(_work_orders).create_work_order(c, actor_id=jefatura, machine_code="MP1", sectors=("BOBINAS", "REBOBINADO"), lines=[
            LineInput("PV-1", MP1_CODES[0], 10, __import__("datetime").date(2026, 11, 1), "MP1"), LineInput("PV-2", MP1_ONLY[1], 10, __import__("datetime").date(2026, 11, 1), "RB1")])
        internal(_work_orders).publish_work_order(c, actor_id=jefatura, work_order_id=view.id, sectors=("BOBINAS", "REBOBINADO"))
        for body in ({"dry_run": True}, {"dry_run": False, "plan_hash": "a" * 64}):
            reply = await self.post(str(view.id), body)
            self.assertEqual((reply.status, reply.json()["code"]), (404, "WORK_ORDER_NOT_FOUND"), body)
            self.assertNotIn("rb1", reply.text.lower())
        self.assertEqual(self.active_count(), 0)

    async def test_individual_activation_keeps_working_with_the_gate_off(self):
        self.gate(False)
        jefatura = await self.cookie("JEFATURA")
        order = (await call("POST", "/api/work-orders", json_body=base.order_body("MP1", 2), cookie=jefatura)).json()
        order = (await call("POST", f"/api/work-orders/{order['id']}/publish", cookie=jefatura)).json()
        self.assertEqual((await self.activate(order, 0)).status, 201)
        second = await self.activate(order, 1)
        self.assertEqual((second.status, second.json()["finished_assignment_id"] is not None), (201, True))  # historical replacement


if __name__ == "__main__":
    unittest.main()
