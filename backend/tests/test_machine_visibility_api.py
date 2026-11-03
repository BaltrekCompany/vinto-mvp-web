"""MF13-03.B PR5: contrato HTTP de las consultas filtradas por máquina (asignaciones, líneas operativas, OT y capturas centrales).

OT L1/MP1, L2/MP1, L3/MP3 creada por Jefatura y activada por Supervisión con la activación masiva (PR4), todo por la API. Usuarios de Operación con concesiones
distintas inician sesión de verdad. El modo y la compuerta son ajustes del servidor parcheados en el proceso de prueba; el cliente no puede cambiarlos.
"""

import secrets
import unittest
from unittest.mock import patch
from uuid import uuid4

from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.auth.service import create_user
from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database

try:
    import test_assignments_api as base
except ModuleNotFoundError:
    from tests import test_assignments_api as base

try:
    from scope_helpers import internal
except ModuleNotFoundError:
    from tests.scope_helpers import internal

from app import capture_service

call = base.call
P103, P106 = "VINTO-P1-03", "VINTO-P1-06"
MP3_ONLY = [c for c in base.MP3_CODES if c not in base.MP1_CODES]
F6_VALUES = {"cantidad_fardos": 10, "punto_merma": "recorte_maquina", "tipo_producto": "hoja_doble", "peso_kg": "125.50", "observaciones": "ok"}
SECRETS = ("MP3", "PV-3")


def setUpModule():
    base.STATE["template"] = build_reference_template("vinto_mvapi_tpl")


def tearDownModule():
    if base.STATE.get("template"):
        drop_database(base.STATE["template"])


def mixed_body():
    return {"machine_code": "MP1", "lines": [
        {"pv_reference": "PV-1", "article_code": base.MP1_CODES[0], "quantity": 10, "due_date": "2026-11-01", "machine_code": "MP1"},
        {"pv_reference": "PV-2", "article_code": base.MP1_CODES[1], "quantity": 10, "due_date": "2026-11-01", "machine_code": "MP1"},
        {"pv_reference": "PV-3", "article_code": MP3_ONLY[0], "quantity": 10, "due_date": "2026-11-01", "machine_code": "MP3"}]}


class VisibilityApiTests(base.AssignmentApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        gate = patch.object(settings, "work_orders_multi_machine_enabled", True)
        gate.start()
        self.addCleanup(gate.stop)
        self.supervisor_id = self.users["SUPERVISION"][0].user_id
        jefatura, supervisor = await self.cookie("JEFATURA"), await self.cookie("SUPERVISION")
        created = await call("POST", "/api/work-orders", json_body=mixed_body(), cookie=jefatura)
        self.assertEqual(created.status, 201, created.text)
        self.ot = (await call("POST", f"/api/work-orders/{created.json()['id']}/publish", cookie=jefatura)).json()
        path = f"/api/work-orders/{self.ot['id']}/activate-all"
        plan = (await call("POST", path, json_body={"dry_run": True}, cookie=supervisor)).json()
        done = await call("POST", path, json_body={"dry_run": False, "plan_hash": plan["plan_hash"]}, cookie=supervisor)
        self.assertEqual(done.status, 201, done.text)
        self.assignments = {a["line"]["line_code"]: a for a in done.json()["activated"]}

    async def operator(self, *machines, form=P103, profile="OPERACION", sectors=("BOBINAS",)):
        password = "pw-" + secrets.token_urlsafe(18)
        created = create_user(self.connection, username=f"mvapi.{uuid4().hex[:10]}", display_name="mvapi", profile_code=profile, password=password, sectors=sectors)
        for machine in machines:
            grant_machine_form(self.connection, user_id=created.user_id, machine_code=machine, form_code=form, actor_id=self.supervisor_id)
        reply = await call("POST", "/api/auth/login", json_body={"username": created.username, "password": password})
        self.assertEqual(reply.status, 200)
        return created, reply.set_cookie_value()

    async def lines(self, cookie, path="/api/assignments/operational-lines"):
        reply = await call("GET", path, cookie=cookie)
        self.assertEqual(reply.status, 200, reply.text)
        return sorted(item["assignment"]["line"]["line_code"] for item in reply.json()["lines"])

    async def test_operational_lines_follow_the_machine_grants(self):
        _, mp1 = await self.operator("MP1")
        _, mp3 = await self.operator("MP3")
        _, both = await self.operator("MP1", "MP3")
        _, none = await self.operator()
        _, data = await self.operator(profile="DATA_BALTREK")
        self.assertEqual([await self.lines(c) for c in (mp1, mp3, both, none, data)], [["L1", "L2"], ["L3"], ["L1", "L2", "L3"], [], []])
        for profile in ("JEFATURA", "SUPERVISION"):
            self.assertEqual(await self.lines(await self.cookie(profile)), ["L1", "L2", "L3"], profile)
        self.assertEqual((await call("GET", "/api/assignments/operational-lines")).status, 401)

    async def test_the_line_contract_identifies_machine_order_line_product_assignment_and_shift(self):
        _, both = await self.operator("MP1", "MP3")
        body = (await call("GET", "/api/assignments/operational-lines", cookie=both)).json()
        self.assertEqual(sorted(body), ["lines"])
        item = body["lines"][0]
        self.assertEqual(sorted(item), ["assignment", "assignment_id", "current_shift", "selectable", "stale"])
        self.assertEqual((item["assignment_id"], item["selectable"], item["stale"]), (item["assignment"]["id"], True, False))
        self.assertEqual({k for k in item["assignment"]} >= {"machine", "work_order", "line", "shift", "status"}, True)
        self.assertEqual([(i["assignment"]["machine"]["code"], i["assignment"]["line"]["line_code"], i["assignment"]["work_order"]["number"]) for i in body["lines"]],
                         [("MP1", "L1", self.ot["number"]), ("MP1", "L2", self.ot["number"]), ("MP3", "L3", self.ot["number"])])
        self.assertEqual(len({i["assignment_id"] for i in body["lines"]}), 3)
        text = (await call("GET", "/api/assignments/operational-lines", cookie=both)).text.lower()
        for forbidden in ("machine_id", "shift_schedule", "article_version", "unit_id", "created_by", "updated_by", "password"):
            self.assertNotIn(forbidden, text)

    async def test_a_partially_authorized_operator_gets_no_trace_of_the_other_machine_anywhere(self):
        _, mp1 = await self.operator("MP1")
        seen = []
        for path in ("/api/assignments/operational-lines", "/api/assignments", "/api/assignments?status=active", "/api/assignments/active-lines?machine_code=MP1",
                     f"/api/assignments?work_order_id={self.ot['id']}", "/api/assignments?status=finished", "/api/work-orders", "/api/work-orders?machine_code=MP3"):
            reply = await call("GET", path, cookie=mp1)
            self.assertIn(reply.status, (200, 404), path)
            seen.append((path, reply.text))
        for path, text in seen:
            for secret in SECRETS:
                self.assertNotIn(secret, text.replace("MP1", ""), path)
            self.assertNotIn(MP3_ONLY[0], text, path)

    async def test_manipulated_urls_filters_and_identifiers_do_not_reveal_unauthorized_lines(self):
        _, mp1 = await self.operator("MP1")
        for path in ("/api/assignments/active-lines?machine_code=MP3", "/api/assignments/active?machine_code=MP3"):
            reply = await call("GET", path, cookie=mp1)
            self.assertEqual((reply.status, reply.json()["code"]), (422, "MACHINE_OUTSIDE_SCOPE"), path)
        listing = (await call("GET", "/api/assignments?machine_code=MP3", cookie=mp1)).json()
        self.assertEqual(listing, [])
        mixed = (await call("GET", f"/api/assignments?work_order_id={self.ot['id']}&status=active", cookie=mp1)).json()
        self.assertEqual(sorted(a["line"]["line_code"] for a in mixed), ["L1", "L2"])
        probe = await call("GET", "/api/assignments/operational-lines?machine_code=MP3&work_order_id=" + self.ot["id"], cookie=mp1)
        self.assertEqual(sorted(i["assignment"]["line"]["line_code"] for i in probe.json()["lines"]), ["L1", "L2"])  # parámetros ajenos al contrato se ignoran
        self.assertEqual((await call("GET", f"/api/assignments/{self.assignments['L3']['id']}/finish", cookie=mp1)).status, 405)

    async def test_active_keeps_the_historical_409_for_two_lines_and_never_picks_one(self):
        _, mp1 = await self.operator("MP1")
        reply = await call("GET", "/api/assignments/active?machine_code=MP1", cookie=mp1)
        self.assertEqual((reply.status, reply.json()["code"]), (409, "MULTIPLE_ACTIVE_ASSIGNMENTS"))
        _, mp3 = await self.operator("MP3")
        single = await call("GET", "/api/assignments/active?machine_code=MP3", cookie=mp3)
        self.assertEqual((single.status, single.json()["assignment"]["line"]["line_code"]), (200, "L3"))

    async def test_work_orders_are_never_returned_partially(self):
        mp1_user, mp1 = await self.operator("MP1")
        _, both = await self.operator("MP1", "MP3")
        self.assertEqual((await call("GET", f"/api/work-orders/{self.ot['id']}", cookie=mp1)).status, 404)
        self.assertNotIn(self.ot["number"], (await call("GET", "/api/work-orders", cookie=mp1)).text)
        whole = await call("GET", f"/api/work-orders/{self.ot['id']}", cookie=both)
        self.assertEqual((whole.status, [l["line_code"] for l in whole.json()["baseline"]["lines"]]), (200, ["L1", "L2", "L3"]))
        for profile in ("JEFATURA", "SUPERVISION"):
            self.assertEqual((await call("GET", f"/api/work-orders/{self.ot['id']}", cookie=await self.cookie(profile))).status, 200, profile)

    async def test_central_capture_reads_are_limited_to_authorized_machines(self):
        _, both = await self.operator("MP1", "MP3")
        owner, _ = await self.operator("MP3", form=P106)
        service = internal(capture_service)
        result = service.submit_production_capture(self.connection, actor_id=owner.user_id, capture_id=uuid4(), form_code=P106, assignment_id=self.assignments["L3"]["id"],
                                                   device_key=str(uuid4()), values=F6_VALUES)
        capture_id = str(result.capture.id)
        _, mp1 = await self.operator("MP1", form=P106)
        _, mp3_reader = await self.operator("MP3", form=P106)
        self.assertEqual((await call("GET", f"/api/captures/{capture_id}", cookie=mp1)).status, 404)
        self.assertEqual((await call("GET", f"/api/captures?assignment_id={self.assignments['L3']['id']}", cookie=mp1)).json(), [])
        self.assertEqual((await call("GET", "/api/captures?machine_code=MP3", cookie=mp1)).json(), [])
        self.assertEqual((await call("GET", f"/api/captures/{capture_id}", cookie=mp3_reader)).status, 200)
        self.assertEqual([c["id"] for c in (await call("GET", f"/api/captures?assignment_id={self.assignments['L3']['id']}", cookie=mp3_reader)).json()], [capture_id])

    async def test_revoking_the_grant_hides_the_lines_on_the_next_request(self):
        user, cookie = await self.operator("MP1", "MP3")
        self.assertEqual(await self.lines(cookie), ["L1", "L2", "L3"])
        revoke_machine_form(self.connection, user_id=user.user_id, machine_code="MP3", form_code=P103, actor_id=self.supervisor_id)
        self.assertEqual(await self.lines(cookie), ["L1", "L2"])

    async def test_the_documented_gap_with_the_gate_and_the_reads_mode_off(self):
        """Compuerta apagada y modo off: las rutas HISTÓRICAS conservan el alcance por sector (comportamiento anterior); el contrato operativo nuevo filtra siempre."""
        _, mp1 = await self.operator("MP1")
        with patch.object(settings, "work_orders_multi_machine_enabled", False):
            self.assertEqual(sorted(a["line"]["line_code"] for a in (await call("GET", "/api/assignments?status=active", cookie=mp1)).json()), ["L1", "L2", "L3"])
            self.assertEqual(await self.lines(mp1), ["L1", "L2"])
            with patch.object(settings, "authz_assignment_reads_mode", "enforce"):
                self.assertEqual(sorted(a["line"]["line_code"] for a in (await call("GET", "/api/assignments?status=active", cookie=mp1)).json()), ["L1", "L2"])


if __name__ == "__main__":
    unittest.main()
