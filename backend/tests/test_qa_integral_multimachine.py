"""MF-13-03.B integral QA before deployment: the whole multi-machine journey through the REAL HTTP API (ASGI app, real login cookies, real PostgreSQL triggers).

Jefatura creates and publishes -> Supervisión asks capabilities, previews and activates -> Operación sees the active lines and captures against the right `assignment_id` -> Supervisión finishes
a line -> conflicts, permissions, revocations, shift change, concurrency and idempotency; then the compatible cases with the gate OFF (historical behaviour).
Ephemeral *_test databases with synthetic users. The gate and the AUTHZ modes are server settings patched INSIDE this test process only; the client can never set them. Nothing touches vinto,
vinto_piloto or any server.
"""

import asyncio
import unittest
from unittest.mock import patch

from app import capture_service as _capture_service
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database

try:
    import test_f3_bobbins_api as f3
except ModuleNotFoundError:
    from tests import test_f3_bobbins_api as f3

try:
    from test_assignments_api import BUNDLE, MP1_CODES as MP1, MP3_CODES as MP3
except ModuleNotFoundError:
    from tests.test_assignments_api import BUNDLE, MP1_CODES as MP1, MP3_CODES as MP3

call = f3.call
ARTICLES = {a["code"]: a["version"] for a in BUNDLE.articles}
GRAMMAGE = [c for c in MP1 if ARTICLES[c]["grammage_g_m2"] is not None]
MP3_ONLY = [c for c in MP3 if c not in MP1]
P103 = "VINTO-P1-03"


def setUpModule():
    f3.STATE["template"] = build_reference_template("vinto_qa_tpl")


def tearDownModule():
    if f3.STATE.get("template"):
        drop_database(f3.STATE["template"])


def mixed_body(second_order=False):
    """L1 and L2 on MP1 and L3 on MP3 (needs the gate ON), or a single MP1 line (any gate state)."""
    if second_order:
        return {"machine_code": "MP1", "lines": [{"pv_reference": "PV-X", "article_code": GRAMMAGE[0], "quantity": 5, "due_date": "2026-11-01"}]}
    return {"machine_code": "MP1", "lines": [
        {"pv_reference": "PV-1", "article_code": GRAMMAGE[0], "quantity": 10, "due_date": "2026-11-01", "machine_code": "MP1"},
        {"pv_reference": "PV-2", "article_code": GRAMMAGE[1], "quantity": 20, "due_date": "2026-11-01", "machine_code": "MP1"},
        {"pv_reference": "PV-3", "article_code": MP3_ONLY[0], "quantity": 30, "due_date": "2026-11-01", "machine_code": "MP3"}]}


class Journey(f3.BobbinApiCase):
    GATE = True
    GRANT = True

    async def asyncSetUp(self):
        await super().asyncSetUp()
        patcher = patch.object(settings, "work_orders_multi_machine_enabled", self.GATE)
        patcher.start()
        self.addCleanup(patcher.stop)
        if self.GATE and self.GRANT:  # with the gate ON, Operación only sees machines it holds an active machine-form grant for (PR5): a deployment prerequisite
            operator, admin = self.users["OPERACION"][0].user_id, self.users["DATA_BALTREK"][0].user_id
            self.connection.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(admin),))
            for machine in ("MP1", "MP3"):
                grant_machine_form(self.connection, user_id=operator, machine_code=machine, form_code=P103, actor_id=admin)

    async def api(self, method, path, profile=None, body=None):
        return await call(method, path, json_body=body, cookie=await self.cookie(profile) if profile else None)

    async def order(self, body=None):
        created = await self.api("POST", "/api/work-orders", "JEFATURA", body or mixed_body())
        self.assertEqual(created.status, 201, created.text)
        published = await self.api("POST", f"/api/work-orders/{created.json()['id']}/publish", "JEFATURA")
        self.assertEqual(published.status, 200, published.text)
        return published.json()

    async def activate_all(self, order):
        preview = await self.api("POST", f"/api/work-orders/{order['id']}/activate-all", "SUPERVISION", {"dry_run": True})
        self.assertEqual(preview.status, 200, preview.text)
        confirm = await self.api("POST", f"/api/work-orders/{order['id']}/activate-all", "SUPERVISION", {"dry_run": False, "plan_hash": preview.json()["plan_hash"]})
        return preview, confirm

    def captures_of(self, assignment_id):
        return self.scalar("SELECT count(*) FROM vinto_txn.capture WHERE assignment_id = %s", (assignment_id,))

    def active_codes(self, machine="MP1"):
        return sorted(r[0] for r in self.connection.execute(
            """SELECT l.line_code FROM vinto_txn.assignment a JOIN vinto_master.machine m ON m.id = a.machine_id JOIN vinto_txn.work_order_line l ON l.id = a.work_order_line_id
               WHERE a.status = 'active' AND m.code = %s""", (machine,)).fetchall())


class IntegralGateOnTests(Journey):
    async def test_the_full_journey_from_creation_to_the_loss_of_a_finished_line(self):
        # 1. Jefatura creates and publishes an order with several lines on two machines
        order = await self.order()
        self.assertEqual([(l["line_code"], l["machine"]["code"]) for l in order["baseline"]["lines"]], [("L1", "MP1"), ("L2", "MP1"), ("L3", "MP3")])
        # 2. Supervisión reads the capabilities and previews (read-only); the roles that do not manage orders cannot read them
        caps = await self.api("GET", "/api/work-orders/capabilities", "SUPERVISION")
        self.assertEqual((caps.status, caps.json()), (200, {"multi_machine": True}))
        for profile in ("OPERACION", "CALIDAD", "DATA_BALTREK"):
            self.assertEqual((await self.api("GET", "/api/work-orders/capabilities", profile)).status, 403, profile)
        self.assertEqual((await self.api("GET", "/api/work-orders/capabilities")).status, 401)
        preview, confirm = await self.activate_all(order)
        self.assertEqual((preview.json()["summary"]["activate"], preview.json()["can_confirm"]), (3, True))
        # 3. ... and activates every line of the order in ONE request
        self.assertEqual((confirm.status, confirm.json()["outcome"]), (201, "applied"), confirm.text)
        self.assertEqual((self.active_codes("MP1"), self.active_codes("MP3")), (["L1", "L2"], ["L3"]))
        # 4. Operación identifies the active lines: the historical read refuses to guess, the multi-line read lists them all
        single = await self.api("GET", "/api/assignments/active?machine_code=MP1", "OPERACION")
        self.assertEqual((single.status, single.json()["code"]), (409, "MULTIPLE_ACTIVE_ASSIGNMENTS"))
        lines = await self.api("GET", "/api/assignments/active-lines?machine_code=MP1", "OPERACION")
        self.assertEqual(lines.status, 200, lines.text)
        items = {i["assignment"]["line"]["line_code"]: i for i in lines.json()["assignments"]}
        self.assertEqual(sorted(items), ["L1", "L2"])
        self.assertTrue(all(i["stale"] is False for i in items.values()))
        # 5-6. the operator picks L1 explicitly and the capture is tied to THAT assignment
        l1, l2 = items["L1"]["assignment"], items["L2"]["assignment"]
        first = await self.post(self.payload(l1))
        self.assertEqual(first.status, 201, first.text)
        self.assertEqual((self.captures_of(l1["id"]), self.captures_of(l2["id"])), (1, 0))
        # 7. ... switches to L2 and captures again
        second = await self.post(self.payload(l2))
        self.assertEqual(second.status, 201, second.text)
        self.assertEqual((self.captures_of(l1["id"]), self.captures_of(l2["id"])), (1, 1))
        # 8. Supervisión finishes L1: Operación loses that context, L2 keeps working, history is preserved
        done = await self.api("POST", f"/api/assignments/{l1['id']}/finish", "SUPERVISION")
        self.assertEqual((done.status, done.json()["status"]), (200, "finished"))
        gone = await self.post(self.payload(l1))
        self.assertEqual((gone.status, gone.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))
        self.assertEqual(self.captures_of(l1["id"]), 1, "the earlier capture is history and stays")
        remaining = await self.api("GET", "/api/assignments/active-lines?machine_code=MP1", "OPERACION")
        self.assertEqual([i["assignment"]["line"]["line_code"] for i in remaining.json()["assignments"]], ["L2"])
        back_to_single = await self.api("GET", "/api/assignments/active?machine_code=MP1", "OPERACION")
        self.assertEqual((back_to_single.status, back_to_single.json()["assignment"]["id"]), (200, l2["id"]))
        self.assertEqual((await self.post(self.payload(l2))).status, 201)

    async def test_a_different_work_order_cannot_enter_a_machine_that_has_active_lines(self):
        order = await self.order()
        _, confirm = await self.activate_all(order)
        self.assertEqual(confirm.status, 201)
        other = await self.order(mixed_body(second_order=True))
        direct = await self.api("POST", "/api/assignments/activate", "SUPERVISION", {"work_order_id": other["id"], "baseline_line_id": other["baseline"]["lines"][0]["id"]})
        self.assertEqual((direct.status, direct.json()["code"]), (409, "MACHINE_ACTIVE_WITH_OTHER_WORK_ORDER"))
        bulk = await self.api("POST", f"/api/work-orders/{other['id']}/activate-all", "SUPERVISION", {"dry_run": True})
        self.assertEqual((bulk.status, bulk.json()["can_confirm"], bulk.json()["summary"]["conflicts"]), (200, False, 2))
        blocked = await self.api("POST", f"/api/work-orders/{other['id']}/activate-all", "SUPERVISION", {"dry_run": False, "plan_hash": bulk.json()["plan_hash"]})
        self.assertEqual((blocked.status, blocked.json()["code"]), (409, "ACTIVATION_BLOCKED"))
        self.assertEqual(self.active_codes("MP1"), ["L1", "L2"], "the first order is untouched")

    async def test_permissions_per_profile_and_session(self):
        order = await self.order()
        for profile in ("OPERACION", "CALIDAD", "DATA_BALTREK", "JEFATURA"):
            denied = await self.api("POST", f"/api/work-orders/{order['id']}/activate-all", profile, {"dry_run": True})
            self.assertEqual(denied.status, 403, profile)
        self.assertEqual((await self.api("POST", f"/api/work-orders/{order['id']}/activate-all", None, {"dry_run": True})).status, 401)
        for profile in ("SUPERVISION", "OPERACION", "CALIDAD"):
            created = await self.api("POST", "/api/work-orders", profile, mixed_body())
            self.assertEqual(created.status, 403, f"{profile} must not create orders")
        self.assertEqual(self.active_codes(), [])

    async def test_a_revoked_machine_form_grant_blocks_the_capture_without_touching_the_line(self):
        order = await self.order()
        _, confirm = await self.activate_all(order)
        l1 = confirm.json()["activated"][0]
        operator, admin = self.users["OPERACION"][0].user_id, self.users["DATA_BALTREK"][0].user_id
        self.connection.execute("SELECT set_config('vinto.actor_id', %s, false)", (str(admin),))
        grant_machine_form(self.connection, user_id=operator, machine_code="MP1", form_code=P103, actor_id=admin)
        with patch.object(settings, "authz_bobbin_production_mode", "enforce"):
            self.assertEqual((await self.post(self.payload(l1))).status, 201)
            revoke_machine_form(self.connection, user_id=operator, machine_code="MP1", form_code=P103, actor_id=admin)
            denied = await self.post(self.payload(l1))
        self.assertEqual(denied.status, 403, denied.text)
        self.assertEqual(self.captures_of(l1["id"]), 1)
        self.assertEqual(self.active_codes("MP1"), ["L1", "L2"])

    async def test_a_shift_or_date_change_makes_the_lines_stale_and_rejects_the_capture(self):
        order = await self.order()
        _, confirm = await self.activate_all(order)
        l1 = confirm.json()["activated"][0]
        later = self.scalar("SELECT clock_timestamp() + interval '2 days'")
        with patch.object(_capture_service, "_now", return_value=later), patch("app.assignments.service._now", return_value=later):
            lines = await self.api("GET", "/api/assignments/active-lines?machine_code=MP1", "OPERACION")
            self.assertTrue(all(i["stale"] is True for i in lines.json()["assignments"]))
            stale = await self.post(self.payload(l1))
        self.assertEqual((stale.status, stale.json()["code"]), (409, "ASSIGNMENT_STALE"))
        self.assertEqual(self.captures_of(l1["id"]), 0)

    async def test_idempotency_retries_replays_and_concurrent_double_submits(self):
        order = await self.order()
        preview, confirm = await self.activate_all(order)
        again = await self.api("POST", f"/api/work-orders/{order['id']}/activate-all", "SUPERVISION", {"dry_run": False, "plan_hash": preview.json()["plan_hash"]})
        self.assertEqual((again.status, again.json()["outcome"]), (200, "already_in_effect"), again.text)
        l1, l2 = confirm.json()["activated"][0], confirm.json()["activated"][1]
        body = self.payload(l1)
        first, replay = await self.post(body), await self.post(body)
        self.assertEqual((first.status, replay.status), (201, 200))
        self.assertEqual(self.captures_of(l1["id"]), 1)
        shared = self.payload(l2)
        both = await asyncio.gather(self.post(shared), self.post(shared))
        self.assertEqual(sorted(r.status for r in both), [200, 201], [r.text for r in both])
        self.assertEqual(self.captures_of(l2["id"]), 1)

    async def test_concurrent_captures_on_both_lines_and_a_finish_race(self):
        order = await self.order()
        _, confirm = await self.activate_all(order)
        l1, l2 = confirm.json()["activated"][0], confirm.json()["activated"][1]
        both = await asyncio.gather(self.post(self.payload(l1)), self.post(self.payload(l2)), self.post(self.payload(l1)), self.post(self.payload(l2)))
        self.assertEqual([r.status for r in both], [201] * 4, [r.text for r in both])
        self.assertEqual((self.captures_of(l1["id"]), self.captures_of(l2["id"])), (2, 2))
        race = await asyncio.gather(self.post(self.payload(l1)), self.api("POST", f"/api/assignments/{l1['id']}/finish", "SUPERVISION"))
        self.assertEqual(race[1].status, 200)
        self.assertIn(race[0].status, (201, 409), race[0].text)
        self.assertEqual(self.captures_of(l1["id"]), 2 + (1 if race[0].status == 201 else 0))


class IntegralGatePrerequisiteTests(Journey):
    """DEPLOYMENT PREREQUISITE found by this QA: with the gate ON, an Operación user with NO active machine-form grant loses the historical reads entirely."""
    GRANT = False

    async def test_without_machine_form_grants_operacion_sees_no_machine_once_the_gate_is_on(self):
        order = await self.order()
        _, confirm = await self.activate_all(order)
        self.assertEqual(confirm.status, 201)
        historical = await self.api("GET", "/api/assignments/active?machine_code=MP1", "OPERACION")
        self.assertEqual((historical.status, historical.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        lines = await self.api("GET", "/api/assignments/active-lines?machine_code=MP1", "OPERACION")
        self.assertEqual((lines.status, lines.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"))
        listing = await self.api("GET", "/api/assignments/operational-lines", "OPERACION")
        self.assertEqual((listing.status, listing.json()["lines"]), (200, []))
        # Supervisión is not affected: it keeps its sector scope
        self.assertEqual((await self.api("GET", "/api/assignments/active-lines?machine_code=MP1", "SUPERVISION")).status, 200)


class PredeployPreflightTests(Journey):
    """The consolidated read-only pre-deployment SQL: it reports what needs a decision and writes NOTHING."""
    GRANT = False

    def run_preflight(self):
        import pathlib
        text = (pathlib.Path(__file__).resolve().parents[1] / "preflights" / "mf13_03b_verify_after_migrate.sql").read_text(encoding="utf-8")
        results = []
        with self.connection.transaction():
            self.connection.execute("SET TRANSACTION READ ONLY")  # any write would fail: the script is provably read only
            for statement in text.split(";\n"):
                if all(line.startswith("--") or not line.strip() for line in statement.splitlines()):
                    continue  # only comments
                results.append(self.connection.execute(statement).fetchall())
        return results

    async def test_it_flags_operators_without_grants_and_machines_with_several_active_rows_and_changes_nothing(self):
        clean = self.run_preflight()
        self.assertEqual(clean[0][0][:2], (12, 12))
        self.assertEqual(clean[0][0][2], "O")
        self.assertTrue(any(row[2] == "OPERACION" for row in clean[1]), "an active OPERACION user with no grant is reported")
        order = await self.order()
        _, confirm = await self.activate_all(order)
        self.assertEqual(confirm.status, 201)
        before = self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a ORDER BY id").fetchall()
        flagged = self.run_preflight()
        self.assertEqual([(r[0], r[1], r[2]) for r in flagged[2]], [("MP1", 2, 1)])
        self.assertEqual(flagged[3], [], "no impossible state")
        self.assertEqual(self.connection.execute("SELECT to_jsonb(a) FROM vinto_txn.assignment a ORDER BY id").fetchall(), before)


class IntegralGateOffTests(Journey):
    """The compatible cases with the gate OFF: historical behaviour, and the database now backs it (0012)."""
    GATE = False

    async def test_the_gate_off_journey_keeps_one_active_assignment_per_machine(self):
        caps = await self.api("GET", "/api/work-orders/capabilities", "JEFATURA")
        self.assertEqual((caps.status, caps.json()), (200, {"multi_machine": False}))
        refused = await self.api("POST", "/api/work-orders", "JEFATURA", mixed_body())
        self.assertEqual((refused.status, refused.json().get("code")), (422, "MULTI_MACHINE_DISABLED"), refused.text)
        order = await self.order({"machine_code": "MP1", "lines": [
            {"pv_reference": "PV-1", "article_code": GRAMMAGE[0], "quantity": 10, "due_date": "2026-11-01"},
            {"pv_reference": "PV-2", "article_code": GRAMMAGE[1], "quantity": 20, "due_date": "2026-11-01"}]})
        bulk = await self.api("POST", f"/api/work-orders/{order['id']}/activate-all", "SUPERVISION", {"dry_run": True})
        self.assertEqual((bulk.status, bulk.json().get("code")), (422, "MULTI_MACHINE_DISABLED"))
        lines = order["baseline"]["lines"]
        a1 = await self.api("POST", "/api/assignments/activate", "SUPERVISION", {"work_order_id": order["id"], "baseline_line_id": lines[0]["id"]})
        self.assertEqual(a1.status, 201, a1.text)
        a2 = await self.api("POST", "/api/assignments/activate", "SUPERVISION", {"work_order_id": order["id"], "baseline_line_id": lines[1]["id"]})
        self.assertEqual(a2.status, 201, a2.text)
        self.assertEqual(a2.json()["finished_assignment_id"], a1.json()["assignment"]["id"], "activating another line REPLACES the previous one")
        self.assertEqual(self.active_codes(), ["L2"])
        single = await self.api("GET", "/api/assignments/active?machine_code=MP1", "OPERACION")
        self.assertEqual((single.status, single.json()["assignment"]["id"]), (200, a2.json()["assignment"]["id"]))
        self.assertEqual((await self.post(self.payload(a2.json()["assignment"]))).status, 201)
        old = await self.post(self.payload(a1.json()["assignment"]))
        self.assertEqual((old.status, old.json()["code"]), (409, "ASSIGNMENT_NOT_ACTIVE"))

    async def test_the_database_refuses_a_second_active_row_even_for_a_writer_that_bypasses_the_service(self):
        order = await self.order({"machine_code": "MP1", "lines": [
            {"pv_reference": "PV-1", "article_code": GRAMMAGE[0], "quantity": 10, "due_date": "2026-11-01"},
            {"pv_reference": "PV-2", "article_code": GRAMMAGE[1], "quantity": 20, "due_date": "2026-11-01"}]})
        first = await self.api("POST", "/api/assignments/activate", "SUPERVISION", {"work_order_id": order["id"], "baseline_line_id": order["baseline"]["lines"][0]["id"]})
        self.assertEqual(first.status, 201)
        import psycopg
        with self.assertRaises(psycopg.Error) as caught:
            with self.connection.transaction():
                self.connection.execute("SELECT set_config('vinto.actor_id', %s, true)", (str(self.users["SUPERVISION"][0].user_id),))
                self.connection.execute(
                    """INSERT INTO vinto_txn.assignment (work_order_line_id, machine_id, shift_schedule_id, operating_date, assigned_by)
                       SELECT l.id, l.machine_id, a.shift_schedule_id, a.operating_date, a.assigned_by FROM vinto_txn.assignment a, vinto_txn.work_order_line l
                        JOIN vinto_txn.work_order_version v ON v.id = l.work_order_version_id WHERE v.work_order_id = %s AND v.kind = 'operational' AND l.line_code = 'L2' LIMIT 1""",
                    (order["id"],))
        self.assertEqual(caught.exception.sqlstate, "23P01")


if __name__ == "__main__":
    unittest.main()
