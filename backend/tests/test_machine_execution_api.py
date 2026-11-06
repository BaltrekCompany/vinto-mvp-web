"""E1-06 HTTP contract: effective MF13 machine grants, no leaked production state."""
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database

try:
    import test_machine_visibility_api as base
except ModuleNotFoundError:
    from tests import test_machine_visibility_api as base

call = base.call
PATH = "/api/assignments/execution-status"


def setUpModule():
    base.base.STATE["template"] = build_reference_template("vinto_e106api_tpl")


def tearDownModule():
    if base.base.STATE.get("template"):
        drop_database(base.base.STATE["template"])
        base.base.STATE.pop("template", None)


class OperationExecutionHttpTests(base.base.AssignmentApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        for setting in ("work_order_line_execution_enabled", "work_orders_multi_machine_enabled"):
            flag = patch.object(settings, setting, True)
            flag.start()
            self.addCleanup(flag.stop)
        self.supervisor_id = self.users["SUPERVISION"][0].user_id
        head = await self.cookie("JEFATURA")
        supervisor = await self.cookie("SUPERVISION")
        created = await call("POST", "/api/work-orders",
                             json_body=base.mixed_body(), cookie=head)
        self.assertEqual(created.status, 201, created.text)
        published = await call("POST", "/api/work-orders/" + created.json()["id"] + "/publish", cookie=head)
        self.assertEqual(published.status, 200, published.text)
        self.ot = published.json()
        target = "/api/work-orders/" + self.ot["id"] + "/activate-all"
        preview = await call("POST", target, json_body={"dry_run": True}, cookie=supervisor)
        self.assertEqual(preview.status, 200, preview.text)
        done = await call("POST", target, json_body={"dry_run": False, "plan_hash": preview.json()["plan_hash"]}, cookie=supervisor)
        self.assertEqual(done.status, 201, done.text)
        self.assignments = {a["line"]["line_code"]: a for a in done.json()["activated"]}

    async def operator(self, *machines):
        password = "pw-" + base.secrets.token_urlsafe(18)
        created = base.create_user(
            self.connection, username="e106." + base.uuid4().hex[:10],
            display_name="E1-06 QA", profile_code="OPERACION",
            password=password, sectors=("BOBINAS",))
        for machine in machines:
            base.grant_machine_form(
                self.connection, user_id=created.user_id, machine_code=machine,
                form_code=base.P103, actor_id=self.supervisor_id)
        reply = await call("POST", "/api/auth/login",
                           json_body={"username": created.username, "password": password})
        self.assertEqual(reply.status, 200, reply.text)
        return created, reply.set_cookie_value()

    async def get_status(self, machine, cookie):
        return await call("GET", PATH + "?machine_code=" + machine, cookie=cookie)

    async def test_operator_only_gets_its_granted_machine(self):
        _, mp1 = await self.operator("MP1")
        reply = await self.get_status("MP1", mp1)
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual(reply.json()["line_execution"], True)
        self.assertEqual(
            {r["assignment_id"]: r["status"] for r in reply.json()["assignments"]},
            {self.assignments["L1"]["id"]: "enabled", self.assignments["L2"]["id"]: "enabled"})
        self.assertEqual((await self.get_status("MP3", mp1)).json()["code"], "MACHINE_OUTSIDE_SCOPE")
        for secret in base.SECRETS:
            self.assertNotIn(secret, reply.text)

    async def test_operator_sees_started_not_other_enabled_line(self):
        _, mp1 = await self.operator("MP1")
        supervisor = await self.cookie("SUPERVISION")
        order_id = self.ot["id"]
        started = await call("POST", "/api/work-orders/" + order_id + "/lines/L1/start",
                             json_body={"assignment_id": self.assignments["L1"]["id"]}, cookie=supervisor)
        self.assertEqual(started.status, 200, started.text)
        reply = await self.get_status("MP1", mp1)
        self.assertEqual({r["assignment_id"]: r["status"] for r in reply.json()["assignments"]},
                         {self.assignments["L1"]["id"]: "in_production", self.assignments["L2"]["id"]: "enabled"})
        finished = await call("POST", "/api/work-orders/" + order_id + "/lines/L1/finish", cookie=supervisor)
        self.assertEqual(finished.status, 200, finished.text)
        remaining = (await self.get_status("MP1", mp1)).json()["assignments"]
        self.assertEqual(remaining, [{"assignment_id": self.assignments["L2"]["id"], "status": "enabled"}])

    async def test_without_machine_grant_the_operator_cannot_read(self):
        _, none = await self.operator()
        reply = await self.get_status("MP1", none)
        self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))

    async def test_old_assignment_gate_off_does_not_change_historical_endpoints(self):
        _, mp1 = await self.operator("MP1")
        with patch.object(settings, "work_order_line_execution_enabled", False):
            state = await self.get_status("MP1", mp1)
            self.assertEqual((state.status, state.json()), (200, {"line_execution": False, "assignments": []}))
            old = await call("GET", "/api/assignments/active-lines?machine_code=MP1", cookie=mp1)
            self.assertEqual(old.status, 200)
            self.assertEqual(sorted(old.json()), ["assignments", "current_shift"])
            self.assertEqual(len(old.json()["assignments"]), 2)

    async def test_endpoint_requires_valid_session(self):
        self.assertEqual((await call("GET", PATH + "?machine_code=MP1")).status, 401)
        self.assertEqual((await call("GET", PATH + "?machine_code=MP1", cookie="invalid")).status, 401)


if __name__ == "__main__":
    unittest.main()
