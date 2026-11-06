"""E1-07 ASGI contract, real sessions & permission checks, isolated PG17."""
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database

try:
    import test_work_orders_multimachine_api as base
except ModuleNotFoundError:
    from tests import test_work_orders_multimachine_api as base


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_e107api_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])
        base.STATE.pop("template", None)


class CloseOrderApiTests(base.MultiMachineApiCase):
    async def asyncSetUp(self):
        for option in ("work_order_line_execution_enabled", "work_orders_multi_machine_enabled"):
            flag = patch.object(settings, option, True)
            flag.start()
            self.addCleanup(flag.stop)
        # No test should inherit an outstanding assignment from a prior case.
        self.connection.execute(
            "UPDATE vinto_txn.assignment SET status='finished', finished_at=clock_timestamp() WHERE status='active'")

    async def published_order(self, count=2):
        lines = [base.body_line(base.MP1_CODES[i], "MP1") for i in range(count)]
        created = await self.post("/api/work-orders", base.order_body(lines))
        self.assertEqual(created.status, 201, created.text)
        order_id = created.json()["id"]
        published = await self.post("/api/work-orders/" + order_id + "/publish")
        self.assertEqual(published.status, 200, published.text)
        return published.json()

    async def activate(self, order, index):
        baseline_id = order["baseline"]["lines"][index]["id"]
        response = await self.post("/api/assignments/activate", {
            "work_order_id": order["id"], "baseline_line_id": baseline_id}, user="SUPERVISION")
        self.assertEqual(response.status, 201, response.text)
        return response.json()["assignment"]["id"]

    async def start(self, order, index, assignment_id):
        code = order["baseline"]["lines"][index]["line_code"]
        path = "/api/work-orders/" + order["id"] + "/lines/" + code + "/start"
        result = await self.post(path, {"assignment_id": assignment_id}, user="SUPERVISION")
        self.assertEqual(result.status, 200, result.text)

    async def finish(self, order, index):
        code = order["baseline"]["lines"][index]["line_code"]
        result = await self.post(
            "/api/work-orders/" + order["id"] + "/lines/" + code + "/finish",
            user="SUPERVISION")
        self.assertEqual(result.status, 200, result.text)

    async def close(self, order, role="SUPERVISION"):
        return await self.post("/api/work-orders/" + order["id"] + "/close", user=role)

    async def test_only_supervision_can_close_real_ot(self):
        order = await self.published_order(1)
        for role in ("JEFATURA", "JEFATURA_BOBINAS", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            reply = await self.close(order, role)
            self.assertEqual(reply.status, 403, role)
        unauthenticated = await base.call("POST", "/api/work-orders/" + order["id"] + "/close")
        self.assertEqual(unauthenticated.status, 401)
        self.assertEqual((await self.close(order)).json()["code"], "WORK_ORDER_CLOSE_INVALID_STATE")

    async def test_pending_lines_return_safe_codes_and_no_state_change(self):
        order = await self.published_order(2)
        await self.activate(order, 0)
        await self.activate(order, 1)
        denied = await self.close(order)
        self.assertEqual(denied.status, 409)
        self.assertEqual(denied.json()["code"], "WORK_ORDER_CLOSE_PENDING_LINES")
        self.assertEqual(denied.json()["pending_lines"], ["L1", "L2"])
        self.assertEqual((await self.get("/api/work-orders/" + order["id"])).json()["status"], "in_progress")

    async def test_close_after_all_finish_and_retry_does_not_rewrite(self):
        order = await self.published_order(1)
        assignment = await self.activate(order, 0)
        await self.start(order, 0, assignment)
        await self.finish(order, 0)
        response = await self.close(order)
        self.assertEqual((response.status, response.json()["status"]), (200, "closed"))
        after = self.scalar("SELECT updated_at FROM vinto_txn.work_order WHERE id=%s", (order["id"],))
        again = await self.close(order)
        self.assertEqual((again.status, again.json()["status"]), (200, "closed"))
        self.assertEqual(self.scalar(
            "SELECT updated_at FROM vinto_txn.work_order WHERE id=%s", (order["id"],)), after)

    async def test_close_disabled_keeps_old_behavior(self):
        order = await self.published_order(1)
        with patch.object(settings, "work_order_line_execution_enabled", False):
            unavailable = await self.close(order)
        self.assertEqual((unavailable.status, unavailable.json()["code"]), (422, "LINE_EXECUTION_DISABLED"))


if __name__ == "__main__":
    unittest.main()
