"""MF13-03.B PR3: HTTP contract of /api/assignments with several active lines of one work order.

Shares the ASGI scaffolding of test_assignments_api. The gate is a server setting patched in the test process; the client can never set it.
"""

import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database

try:
    import test_assignments_api as base
except ModuleNotFoundError:
    from tests import test_assignments_api as base

call = base.call


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_swapi_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])


class SameOrderApiTests(base.AssignmentApiCase):
    def gate(self, value=True):
        patcher = patch.object(settings, "work_orders_multi_machine_enabled", value)
        patcher.start()
        self.addCleanup(patcher.stop)

    async def active(self, path="/api/assignments/active?machine_code=MP1", profile="SUPERVISION"):
        return await call("GET", path, cookie=await self.cookie(profile))

    async def test_two_lines_of_one_order_are_active_and_activation_reports_no_ambiguous_replacement(self):
        self.gate()
        order = await self.published_order(lines=2)
        first, second = await self.activate(order, 0), await self.activate(order, 1)
        self.assertEqual((first.status, second.status), (201, 201))
        body = second.json()
        self.assertEqual((body["created"], body["finished_assignment_id"], body["finished_assignment_ids"]), (True, None, []))
        listing = (await call("GET", "/api/assignments?status=active&machine_code=MP1", cookie=await self.cookie("SUPERVISION"))).json()
        self.assertEqual(sorted(a["line"]["line_code"] for a in listing), ["L1", "L2"])

    async def test_another_order_on_the_machine_is_a_409_and_the_first_order_is_untouched(self):
        self.gate()
        one, two = await self.published_order(lines=1), await self.published_order(lines=1)
        await self.activate(one, 0)
        reply = await self.activate(two, 0)
        self.assertEqual(reply.status, 409)
        self.assertEqual(reply.json()["code"], "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER")
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 1)

    async def test_legacy_active_is_a_409_with_several_lines_and_active_lines_lists_them_all(self):
        self.gate()
        order = await self.published_order(lines=2)
        await self.activate(order, 0)
        await self.activate(order, 1)
        legacy = await self.active()
        self.assertEqual(legacy.status, 409)
        self.assertNotIn('"assignment"', legacy.text)  # no arbitrary line leaks into the error
        lines = await self.active("/api/assignments/active-lines?machine_code=MP1")
        self.assertEqual(lines.status, 200)
        body = lines.json()
        self.assertEqual(sorted(body), ["assignments", "current_shift"])
        self.assertEqual([i["assignment"]["line"]["line_code"] for i in body["assignments"]], ["L1", "L2"])
        self.assertEqual([i["stale"] for i in body["assignments"]], [False, False])
        self.assertEqual(sorted(body["assignments"][0]), ["assignment", "stale"])

    async def test_with_zero_or_one_active_line_the_legacy_contract_is_unchanged(self):
        self.gate(False)
        empty = (await self.active()).json()
        self.assertEqual((sorted(empty), empty["assignment"]), (["assignment", "current_shift", "stale"], None))
        order = await self.published_order(lines=1)
        await self.activate(order, 0)
        one = (await self.active()).json()
        self.assertEqual(sorted(one), ["assignment", "current_shift", "stale"])
        self.assertEqual((one["assignment"]["line"]["line_code"], one["stale"]), ("L1", False))
        lines = (await self.active("/api/assignments/active-lines?machine_code=MP1")).json()
        self.assertEqual(len(lines["assignments"]), 1)

    async def test_gate_off_keeps_the_historical_replacement_through_http(self):
        self.gate(False)
        order = await self.published_order(lines=2)
        first = (await self.activate(order, 0)).json()
        second = await self.activate(order, 1)
        self.assertEqual((second.status, second.json()["finished_assignment_id"]), (201, first["assignment"]["id"]))
        self.assertEqual((await self.active()).json()["assignment"]["line"]["line_code"], "L2")

    async def test_with_the_gate_off_and_several_active_lines_the_server_refuses_to_pick(self):
        self.gate(True)
        order = await self.published_order(lines=2)
        await self.activate(order, 0)
        await self.activate(order, 1)
        self.gate(False)
        other = await self.published_order(lines=1)
        reply = await self.activate(other, 0)
        self.assertEqual(reply.status, 409)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 2)
        self.assertEqual((await self.active()).status, 409)
        self.assertEqual((await self.active("/api/assignments/active-lines?machine_code=MP1")).status, 200)

    async def test_the_client_cannot_turn_the_gate_on_nor_send_machine_data(self):
        order = await self.published_order(lines=2)
        for extra in ({"machine_code": "MP3"}, {"work_orders_multi_machine_enabled": True}, {"operational_line_id": order["baseline"]["lines"][0]["id"]}):
            body = {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"], **extra}
            self.assertEqual((await self.activate(order, body=body)).status, 422, extra)
        self.assertEqual(self.scalar("SELECT count(*) FROM vinto_txn.assignment WHERE status='active'"), 0)

    async def test_only_supervision_activates_and_every_read_profile_can_list_the_lines(self):
        self.gate()
        order = await self.published_order(lines=1)
        for profile in ("JEFATURA", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            self.assertEqual((await self.activate(order, 0, profile=profile)).status, 403, profile)
        await self.activate(order, 0)
        for profile in base.PROFILES:  # PR5: gestores ven su sector; Operación, Calidad y DATA sin concesiones de máquina no (misma respuesta que fuera de alcance)
            expected = 200 if profile in ("JEFATURA", "SUPERVISION") else 422
            self.assertEqual((await self.active("/api/assignments/active-lines?machine_code=MP1", profile)).status, expected, profile)


if __name__ == "__main__":
    unittest.main()
