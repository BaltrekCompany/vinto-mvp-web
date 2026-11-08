"""E2-D1 HTTP and E2-C2 tests against disposable PostgreSQL 17 databases."""
import unittest
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from app.assignments import service as assignment_service
from app.config import settings

try:
    import test_work_orders_api as api
except ModuleNotFoundError:
    from tests import test_work_orders_api as api


def setUpModule():
    api.STATE["template"] = api.build_reference_template("vinto_e2d1http_tpl")


def tearDownModule():
    template = api.STATE.pop("template", None)
    if template:
        api.drop_database(template)


class E2D1HttpTests(api.WorkOrderApiCase):
    def setUp(self):
        for target, name, value in (
            (settings, "work_order_line_execution_enabled", True),
            (settings, "work_orders_multi_machine_enabled", True),
            (assignment_service, "_now", datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)),
        ):
            p = patch.object(target, name, return_value=value) if name == "_now" else patch.object(target, name, value)
            p.start()
            self.addCleanup(p.stop)

    async def running_order(self):
        jef = await self.cookie("JEFATURA")
        sup = await self.cookie("SUPERVISION")
        created = await self.create(body=api.payload(lines=[
            api.line_body(api.MP1_CODES[0], "PV-L1", 100, "2026-11-10"),
            api.line_body(api.MP1_CODES[1], "PV-L2", 50, "2026-11-11"),
        ]))
        self.assertEqual(created.status, 201, created.text)
        order = created.json()
        published = await api.call("POST", f"/api/work-orders/{order['id']}/publish", cookie=jef)
        self.assertEqual(published.status, 200, published.text)
        order = published.json()
        first = await api.call("POST", "/api/assignments/activate",
                               json_body={"work_order_id": order["id"],
                                          "baseline_line_id": order["baseline"]["lines"][0]["id"]},
                               cookie=sup)
        self.assertEqual(first.status, 201, first.text)
        self.assertEqual(first.json()["assignment"]["operational"]["version_number"], 2)
        return order, first.json()["assignment"]

    def body(self, order, *, index=1, version=2, quantity=None):
        src = order.get("programming") or order["baseline"]
        line = src["lines"][index]
        fields = dict(pv_reference=line["pv_reference"], article_code=line["article"]["code"],
                      quantity=line["quantity"], due_date=line["due_date"])
        return {
            "expected_version": version, "expected": fields,
            "replacement": {**fields, "quantity": quantity if quantity is not None else line["quantity"] + 7},
            "reason": "Ajuste de linea no asignada con trazabilidad completa",
        }

    def url(self, order, code="L2"):
        return f"/api/work-orders/{order['id']}/lines/{code}/reprogram-unassigned-in-progress"

    def versions(self, order):
        return self.scalar("SELECT count(*) FROM vinto_txn.work_order_version WHERE work_order_id=%s",
                           (order["id"],))

    async def test_flag_off_401_403_and_no_side_effects(self):
        order, _ = await self.running_order()
        url, body = self.url(order), self.body(order)
        for profile in ("SUPERVISION", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            reply = await api.call("POST", url, json_body=body, cookie=await self.cookie(profile))
            self.assertEqual(reply.status, 403, (profile, reply.text))
        self.assertEqual((await api.call("POST", url, json_body=body)).status, 401)
        disabled = await api.call("POST", url, json_body=body, cookie=await self.cookie("JEFATURA"))
        self.assertEqual((disabled.status, disabled.json()["code"]), (409, "WORK_ORDER_D1_DISABLED"))
        self.assertEqual(self.versions(order), 2)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.assignment a JOIN vinto_txn.work_order_line l ON l.id=a.work_order_line_id "
            "JOIN vinto_txn.work_order_version v ON v.id=l.work_order_version_id WHERE v.work_order_id=%s",
            (order["id"],)), 1)

    async def test_revise_l2_preserves_l1_and_supervision_receipt(self):
        order, l1 = await self.running_order()
        sup, jef = await self.cookie("SUPERVISION"), await self.cookie("JEFATURA")
        started = await api.call("POST", f"/api/work-orders/{order['id']}/lines/L1/start",
                                 json_body={"assignment_id": l1["id"]}, cookie=sup)
        self.assertEqual(started.status, 200, started.text)
        self.assertEqual(started.json()["status"], "in_production")
        assignment_row = self.connection.execute(
            "SELECT work_order_line_id,status FROM vinto_txn.assignment WHERE id=%s", (l1["id"],)).fetchone()
        with patch.object(settings, "work_order_reprogram_unassigned_in_progress_enabled", True):
            revised = await api.call("POST", self.url(order), json_body=self.body(order), cookie=jef)
        self.assertEqual(revised.status, 200, revised.text)
        new = revised.json()
        self.assertEqual(new["programming"]["version_number"], 3)
        self.assertEqual(new["programming"]["lines"][1]["quantity"], 57)
        self.assertEqual(new["baseline"], order["baseline"])
        self.assertEqual(
            self.connection.execute(
                "SELECT work_order_line_id,status FROM vinto_txn.assignment WHERE id=%s",
                (l1["id"],)).fetchone(), assignment_row)
        self.assertEqual(self.scalar(
            "SELECT status FROM vinto_txn.work_order_line_execution WHERE baseline_line_id=%s",
            (order["baseline"]["lines"][0]["id"],)), "in_production")

        history = await api.call("GET", f"/api/work-orders/{order['id']}/revisions", cookie=jef)
        self.assertEqual(history.status, 200, history.text)
        self.assertEqual((history.json()[0]["version_number"], history.json()[0]["previous_version"],
                          history.json()[0]["line_code"]), (3, 2, "L2"))

        notice = await api.call("GET", "/api/work-orders/supervision-revision-notices", cookie=sup)
        self.assertEqual(notice.status, 200, notice.text)
        ours = [item for item in notice.json() if item["work_order_id"] == order["id"]]
        self.assertEqual(len(ours), 1)
        self.assertEqual((ours[0]["version_number"], ours[0]["line_code"]), (3, "L2"))
        ack = await api.call("POST", f"/api/work-orders/{order['id']}/acknowledge-supervision-revision",
                             json_body={"expected_version": 3}, cookie=sup)
        self.assertEqual(ack.status, 200, ack.text)
        self.assertEqual(ack.json()["version_number"], 3)
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_supervision_revision_receipt r "
            "JOIN vinto_txn.work_order_version v ON v.id=r.version_id "
            "WHERE v.work_order_id=%s AND v.version_number=3", (order["id"],)), 1)

        repeat = await api.call("POST", "/api/assignments/activate",
                                json_body={"work_order_id": order["id"],
                                           "baseline_line_id": order["baseline"]["lines"][0]["id"]},
                                cookie=sup)
        self.assertEqual(repeat.status, 200, repeat.text)
        self.assertEqual(repeat.json()["assignment"]["id"], l1["id"])
        self.assertTrue(repeat.json()["already_active"])

    async def test_invalid_stale_and_already_assigned_are_rejected(self):
        order, _ = await self.running_order()
        sup, jef = await self.cookie("SUPERVISION"), await self.cookie("JEFATURA")
        body = self.body(order)
        with patch.object(settings, "work_order_reprogram_unassigned_in_progress_enabled", True):
            for extra in ({"machine_code": "MP1"}, {"id": str(uuid4())}):
                bad = {**body, "replacement": {**body["replacement"], **extra}}
                self.assertEqual((await api.call("POST", self.url(order), json_body=bad, cookie=jef)).status, 422)
            invalid = await api.call("POST", self.url(order, "L99"), json_body=body, cookie=jef)
            self.assertEqual(invalid.status, 404)
            invalid = await api.call("POST", self.url(order),
                                     json_body={**body, "expected_version": 99}, cookie=jef)
            self.assertEqual((invalid.status, invalid.json()["code"]), (409, "WORK_ORDER_REPROGRAM_CONFLICT"))
            invalid = await api.call("POST", self.url(order),
                                     json_body={**body, "expected": {**body["expected"], "quantity": 999}},
                                     cookie=jef)
            self.assertEqual((invalid.status, invalid.json()["code"]), (409, "WORK_ORDER_REPROGRAM_CONFLICT"))
            self.assertEqual(self.versions(order), 2)
            l2 = await api.call("POST", "/api/assignments/activate",
                                json_body={"work_order_id": order["id"],
                                           "baseline_line_id": order["baseline"]["lines"][1]["id"]}, cookie=sup)
            self.assertEqual(l2.status, 201, l2.text)
            blocked = await api.call("POST", self.url(order), json_body=body, cookie=jef)
            self.assertEqual((blocked.status, blocked.json()["code"]), (409, "WORK_ORDER_D1_BLOCKED"))
            self.assertEqual(self.versions(order), 2)


if __name__ == "__main__":
    unittest.main()
