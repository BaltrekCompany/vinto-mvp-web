"""E2-D2-B1.1 HTTP authorization on disposable PostgreSQL17 databases."""
import secrets
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr
from app.assignments import service as assignment_service
from app.config import settings

try:
    import test_work_orders_api as api
except ModuleNotFoundError:
    from tests import test_work_orders_api as api


def setUpModule():
    api.STATE["template"] = api.build_reference_template("vinto_e2d2b1http_tpl")


def tearDownModule():
    template = api.STATE.pop("template", None)
    if template:
        api.drop_database(template)


class E2D2B1HttpTests(api.WorkOrderApiCase):
    @classmethod
    def setUpClass(cls):
        pass

    @classmethod
    def tearDownClass(cls):
        pass

    def setUp(self):
        self.database = api.copy_database(api.STATE["template"], "vinto_e2d2b1http")
        self.addCleanup(api.drop_database, self.database)
        self.connection = api.connect(self.database)
        self.addCleanup(self.connection.close)
        p = patch.object(settings, "database_url", SecretStr(api.database_url(self.database)))
        p.start()
        self.addCleanup(p.stop)
        self.users, self.cookies = {}, {}
        for profile in api.PROFILES:
            pwd = "pw-" + secrets.token_urlsafe(18)
            actor = api.create_user(
                self.connection, username=f"b11.{profile.lower()}.{uuid4().hex[:6]}",
                display_name=f"B1 {profile}", profile_code=profile,
                password=pwd, sectors=("BOBINAS",))
            self.users[profile] = (actor, pwd)
        for target, name, value in (
            (settings, "work_order_line_execution_enabled", True),
            (settings, "work_orders_multi_machine_enabled", True),
            (assignment_service, "_now", datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)),
        ):
            q = patch.object(target, name, return_value=value) if name == "_now" else patch.object(target, name, value)
            q.start()
            self.addCleanup(q.stop)

    async def target(self):
        jef, sup = await self.cookie("JEFATURA"), await self.cookie("SUPERVISION")
        created = await self.create(body=api.payload(lines=[
            api.line_body(api.MP1_CODES[0], "PV-B1", 50, "2026-11-10")]))
        self.assertEqual(created.status, 201, created.text)
        order = created.json()
        published = await api.call(
            "POST", f"/api/work-orders/{order['id']}/publish", cookie=jef)
        self.assertEqual(published.status, 200, published.text)
        order = published.json()
        activation = await api.call(
            "POST", "/api/assignments/activate",
            json_body={"work_order_id": order["id"],
                       "baseline_line_id": order["baseline"]["lines"][0]["id"]},
            cookie=sup)
        self.assertEqual(activation.status, 201, activation.text)
        return order, activation.json()["assignment"], sup

    def reserve_url(self, order):
        return f"/api/work-orders/{order['id']}/lines/L1/reserve-handoff"

    def reserve_body(self, assignment):
        return {"assignment_id": assignment["id"],
                "expected_version": 2,
                "reason": "Reserva supervisada de linea sin iniciar"}

    async def test_b3_recovery_inbox_and_capability_are_scoped_and_flag_aware(self):
        order, assignment, supervisor = await self.target()
        manager = await self.cookie("JEFATURA")
        capability = "/api/work-orders/handoff-capabilities"
        inbox = "/api/work-orders/handoffs"

        for url in (capability, inbox):
            self.assertEqual((await api.call("GET", url)).status, 401)
            for profile in ("OPERACION", "CALIDAD", "DATA_BALTREK"):
                denied = await api.call("GET", url, cookie=await self.cookie(profile))
                self.assertEqual(denied.status, 403, (profile, denied.text))

        for cookie in (manager, supervisor):
            flag = await api.call("GET", capability, cookie=cookie)
            self.assertEqual((flag.status, flag.json()), (200, {"enabled": False}))
            empty = await api.call("GET", inbox, cookie=cookie)
            self.assertEqual((empty.status, empty.json()), (200, []))

        with patch.object(settings, "work_order_reprogram_handoff_enabled", True):
            for cookie in (manager, supervisor):
                flag = await api.call("GET", capability, cookie=cookie)
                self.assertEqual((flag.status, flag.json()), (200, {"enabled": True}))
            reservation = await api.call(
                "POST", self.reserve_url(order),
                json_body=self.reserve_body(assignment), cookie=supervisor)
            self.assertEqual(reservation.status, 200, reservation.text)
        handoff_id = reservation.json()["handoff_id"]

        # The flag may be OFF again: recovery remains visible, not a secret
        # identifier stored in a browser or sent to the other profile.
        for cookie in (manager, supervisor):
            response = await api.call("GET", inbox, cookie=cookie)
            self.assertEqual(response.status, 200, response.text)
            self.assertEqual(len(response.json()), 1)
            item = response.json()[0]
            self.assertEqual(item["handoff_id"], handoff_id)
            self.assertEqual(item["work_order_id"], order["id"])
            self.assertEqual(item["work_order_number"], order["number"])
            self.assertEqual(item["status"], "pending")
            self.assertEqual(item["line_code"], "L1")
            self.assertEqual(item["machine_code"], "MP1")
            self.assertEqual(item["expected_version"], 2)
            self.assertEqual(item["prior_assignment_id"], assignment["id"])
            self.assertNotIn("requested_by", item)
            self.assertEqual(dict(response.headers).get(b"cache-control"), b"private, no-store")

        # Same functional role, different sector: no order or handoff leak.
        password = "pw-" + secrets.token_urlsafe(18)
        outsider = api.create_user(
            self.connection, username=f"b3.outside.{uuid4().hex[:6]}",
            display_name="Other sector QA", profile_code="SUPERVISION",
            password=password, sectors=("REBOBINADO",))
        self.users["B3_OUTSIDE"] = (outsider, password)
        outside = await self.cookie("B3_OUTSIDE")
        hidden = await api.call("GET", inbox, cookie=outside)
        self.assertEqual((hidden.status, hidden.json()), (200, []))

    async def test_permission_validation_and_disabled_flag(self):
        order, a, sup = await self.target()
        url, body = self.reserve_url(order), self.reserve_body(a)
        self.assertEqual((await api.call("POST", url, json_body=body)).status, 401)
        for profile in ("JEFATURA", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            r = await api.call("POST", url, json_body=body,
                               cookie=await self.cookie(profile))
            self.assertEqual(r.status, 403, (profile, r.text))
        r = await api.call("POST", url, json_body=body, cookie=sup)
        self.assertEqual((r.status, r.json()["code"]),
                         (409, "WORK_ORDER_HANDOFF_DISABLED"))
        self.assertEqual(self.scalar(
            "SELECT count(*) FROM vinto_txn.work_order_line_reprogram_handoff"), 0)

        with patch.object(settings, "work_order_reprogram_handoff_enabled", True):
            for extra in ({"requested_by": str(uuid4())}, {"status": "published"},
                          {"machine_code": "MP1"}):
                r = await api.call(
                    "POST", url, json_body={**body, **extra}, cookie=sup)
                self.assertEqual(r.status, 422, r.text)

    async def test_reservation_blocks_start_then_cancel_releases(self):
        order, a, sup = await self.target()
        url, body = self.reserve_url(order), self.reserve_body(a)
        with patch.object(settings, "work_order_reprogram_handoff_enabled", True):
            reserved = await api.call("POST", url, json_body=body, cookie=sup)
            self.assertEqual(reserved.status, 200, reserved.text)
            info = reserved.json()
            self.assertEqual(info["status"], "pending")
            self.assertEqual(info["prior_assignment_id"], a["id"])
            blocked = await api.call(
                "POST", f"/api/work-orders/{order['id']}/lines/L1/start",
                json_body={"assignment_id": a["id"]}, cookie=sup)
            self.assertEqual((blocked.status, blocked.json()["code"]),
                             (409, "WORK_ORDER_HANDOFF_PENDING"))
            cancel = await api.call(
                "POST", f"/api/work-orders/handoffs/{info['handoff_id']}/cancel",
                json_body={"reason": "Cancelacion supervisada registrada"}, cookie=sup)
            self.assertEqual(cancel.status, 200, cancel.text)
            self.assertEqual(cancel.json()["status"], "cancelled")
            repeat = await api.call(
                "POST", f"/api/work-orders/handoffs/{info['handoff_id']}/cancel",
                json_body={"reason": "Cancelacion supervisada registrada"}, cookie=sup)
            self.assertEqual(repeat.status, 200)
            started = await api.call(
                "POST", f"/api/work-orders/{order['id']}/lines/L1/start",
                json_body={"assignment_id": a["id"]}, cookie=sup)
            self.assertEqual(started.status, 200, started.text)
            self.assertEqual(started.json()["status"], "in_production")

    
    async def test_role_separated_publish_reassign_and_no_early_start(self):
        order,a,sup=await self.target()
        jef=await self.cookie("JEFATURA")
        reserve_body=self.reserve_body(a)
        with patch.object(settings,"work_order_reprogram_handoff_enabled",True):
            reserved=await api.call(
                "POST",self.reserve_url(order),json_body=reserve_body,cookie=sup)
            self.assertEqual(reserved.status,200,reserved.text)
            h=reserved.json()["handoff_id"]
            line=order["baseline"]["lines"][0]
            expected={
                "pv_reference":line["pv_reference"],
                "article_code":line["article"]["code"],
                "quantity":line["quantity"],
                "due_date":line["due_date"],
            }
            publish_body={
                "expected":expected,
                "replacement":{**expected,"quantity":expected["quantity"]+5},
                "reason":"Jefatura confirma nueva version tras relevo",
            }
            publish_url=f"/api/work-orders/handoffs/{h}/publish"
            reassign_url=f"/api/work-orders/handoffs/{h}/reassign"
            self.assertEqual((await api.call(
                "POST",publish_url,json_body=publish_body)).status,401)
            self.assertEqual((await api.call(
                "POST",publish_url,json_body=publish_body,cookie=sup)).status,403)
            self.assertEqual((await api.call(
                "POST",reassign_url,cookie=jef)).status,403)
            invalid=await api.call(
                "POST",publish_url,json_body={
                    **publish_body,"machine_code":"MP1"},cookie=jef)
            self.assertEqual(invalid.status,422,invalid.text)
            published=await api.call(
                "POST",publish_url,json_body=publish_body,cookie=jef)
            self.assertEqual(published.status,200,published.text)
            self.assertEqual(published.json()["version_number"],3)
            self.assertEqual(published.json()["status"],"published")
            self.assertEqual(self.scalar(
                "SELECT status FROM vinto_txn.assignment WHERE id=%s",
                (a["id"],)),"active")
            reassigned=await api.call("POST",reassign_url,cookie=sup)
            self.assertEqual(reassigned.status,200,reassigned.text)
            info=reassigned.json()
            self.assertEqual(info["status"],"reassigned")
            self.assertEqual(info["previous_assignment_id"],a["id"])
            self.assertNotEqual(info["replacement_assignment_id"],a["id"])
            self.assertEqual(self.scalar(
                "SELECT status FROM vinto_txn.assignment WHERE id=%s",
                (a["id"],)),"finished")
            start=await api.call(
                "POST",f"/api/work-orders/{order['id']}/lines/L1/start",
                json_body={"assignment_id":info["replacement_assignment_id"]},
                cookie=sup)
            self.assertEqual((start.status,start.json()["code"]),
                             (409,"WORK_ORDER_HANDOFF_PENDING"))

    async def test_b2_recovery_read_only_supervisor_scope_with_flag_off(self):
        order, a, sup = await self.target()
        with patch.object(settings, "work_order_reprogram_handoff_enabled", True):
            res = await api.call(
                "POST", self.reserve_url(order),
                json_body=self.reserve_body(a), cookie=sup)
            self.assertEqual(res.status, 200, res.text)
        handoff_id = res.json()["handoff_id"]
        url = f"/api/work-orders/handoffs/{handoff_id}"
        self.assertEqual((await api.call("GET", url)).status, 401)
        for profile in ("JEFATURA", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            denied = await api.call(
                "GET", url, cookie=await self.cookie(profile))
            self.assertEqual(denied.status, 403, (profile, denied.text))
        # OFF does not hide or unfreeze the existing reservation.
        with patch.object(settings, "work_order_reprogram_handoff_enabled", False):
            found = await api.call("GET", url, cookie=sup)
            self.assertEqual(found.status, 200, found.text)
            self.assertEqual(found.json()["status"], "pending")
            self.assertEqual(found.json()["recovery_action"],
                             "cancel_pending_or_publish")
            self.assertEqual(found.json()["prior_assignment_id"], a["id"])
            self.assertEqual(found.json()["work_order_id"], order["id"])
            missing = await api.call(
                "GET", f"/api/work-orders/handoffs/{uuid4()}", cookie=sup)
            self.assertEqual(missing.status, 404, missing.text)
            cancel = await api.call(
                "POST", f"{url}/cancel",
                json_body={"reason": "Cancelacion de reserva tras desactivar D2"},
                cookie=sup)
            self.assertEqual(cancel.status, 200, cancel.text)
            after = await api.call("GET", url, cookie=sup)
            self.assertEqual(after.status, 200, after.text)
            self.assertEqual(after.json()["status"], "cancelled")


