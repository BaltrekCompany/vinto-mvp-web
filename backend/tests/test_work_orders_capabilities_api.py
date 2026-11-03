"""MF13-03.B PR6.1: GET /api/work-orders/capabilities (read-only, authenticated, minimum scope).

Reuses the ASGI harness of the PR2 multi-machine API tests (ephemeral *_test database, one user per profile). The server gate is only ever changed through
patch.object on the server setting; the client has no way to change it.
"""

import json
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders.router import router

try:
    import test_work_orders_multimachine_api as wm
except ModuleNotFoundError:
    from tests import test_work_orders_multimachine_api as wm

PATH = "/api/work-orders/capabilities"
call = wm.call


def setUpModule():
    wm.STATE["template"] = build_reference_template("vinto_wmcap_tpl")


def tearDownModule():
    if wm.STATE.get("template"):
        drop_database(wm.STATE["template"])


def headers(reply):
    return {key.decode().lower(): value.decode() for key, value in reply.headers}


class CapabilitiesCase(wm.MultiMachineApiCase):
    def snapshot(self):
        return [self.scalar(f"SELECT count(*) FROM {t}") for t in ("vinto_audit.audit_event", "vinto_txn.work_order", "vinto_txn.work_order_line", "vinto_txn.assignment",
                                                                      "vinto_master.user_machine_form_grant")]


class ValueTests(CapabilitiesCase):
    async def test_the_gate_is_off_by_default_and_the_endpoint_says_so(self):
        self.assertIs(settings.work_orders_multi_machine_enabled, False)
        reply = await self.get(PATH)
        self.assertEqual(reply.status, 200, reply.text)
        self.assertEqual(reply.json(), {"multi_machine": False})

    async def test_with_the_gate_on_in_an_isolated_test_it_says_true(self):
        self.gate(True)
        self.assertEqual((await self.get(PATH)).json(), {"multi_machine": True})
        self.gate(False)
        self.assertEqual((await self.get(PATH)).json(), {"multi_machine": False})

    async def test_only_the_exact_boolean_true_counts(self):
        for value in (1, "true", "yes", "1", object(), None):
            with patch.object(settings, "work_orders_multi_machine_enabled", value):
                self.assertEqual((await self.get(PATH)).json(), {"multi_machine": False}, repr(value))

    async def test_the_body_publishes_nothing_but_the_capability(self):
        self.gate(True)
        reply = await self.get(PATH)
        self.assertEqual(sorted(reply.json()), ["multi_machine"])
        text = reply.text.lower()
        for forbidden in ("database", "secret", "password", "enforce", "authz", "token", "version", "mode"):
            self.assertNotIn(forbidden, text)


class AccessTests(CapabilitiesCase):
    async def test_a_missing_or_invalid_session_is_a_401(self):
        self.assertEqual((await call("GET", PATH)).status, 401)
        self.assertEqual((await call("GET", PATH, cookie="not-a-real-session")).status, 401)

    async def test_jefatura_and_supervision_may_ask(self):
        for user in ("JEFATURA", "JEFATURA_BOBINAS", "SUPERVISION"):
            reply = await self.get(PATH, user)
            self.assertEqual((reply.status, reply.json()), (200, {"multi_machine": False}), user)

    async def test_profiles_that_neither_manage_nor_activate_orders_are_a_403(self):
        self.gate(True)
        for user in ("OPERACION", "CALIDAD", "DATA_BALTREK"):
            reply = await self.get(PATH, user)
            self.assertEqual(reply.status, 403, user)
            self.assertNotIn("multi_machine", reply.text, "a denied caller learns nothing about the gate")


class HeadersAndRoutingTests(CapabilitiesCase):
    async def test_the_response_is_never_cached(self):
        reply = await self.get(PATH)
        self.assertEqual(headers(reply)["cache-control"], "private, no-store")
        self.assertTrue(headers(reply)["content-type"].startswith("application/json"))

    async def test_the_static_route_wins_over_the_order_id_route(self):
        paths = [route.path for route in router.routes]  # el orden en que FastAPI evalúa las rutas del router (los paths ya incluyen el prefijo)
        self.assertLess(paths.index("/api/work-orders/capabilities"), paths.index("/api/work-orders/{work_order_id}"))
        reply = await self.get(PATH)
        self.assertEqual(reply.status, 200)
        self.assertNotIn("WORK_ORDER_NOT_FOUND", reply.text)

    async def test_ordinary_order_detail_still_resolves(self):
        created = await self.post("/api/work-orders", wm.order_body([wm.body_line(wm.MP1_CODES[0])]))
        self.assertEqual(created.status, 201, created.text)
        detail = await self.get(f"/api/work-orders/{created.json()['id']}")
        self.assertEqual((detail.status, detail.json()["number"]), (200, created.json()["number"]))
        missing = await self.get("/api/work-orders/00000000-0000-4000-8000-000000000000")
        self.assertEqual((missing.status, missing.json()["code"]), (404, "WORK_ORDER_NOT_FOUND"))


class ClientCannotChangeItTests(CapabilitiesCase):
    async def test_query_string_and_headers_cannot_flip_the_value(self):
        cookie = await self.cookie("JEFATURA")
        extra = (("x-multi-machine", "true"), ("x-work-orders-multi-machine-enabled", "true"), ("x-forwarded-multi-machine", "1"))
        for query in ("", "?multi_machine=true", "?work_orders_multi_machine_enabled=true", "?enabled=1&multi_machine=1"):
            reply = await call("GET", PATH + query, cookie=cookie, extra_headers=extra)
            self.assertEqual((reply.status, reply.json()), (200, {"multi_machine": False}), query)
        self.assertIs(settings.work_orders_multi_machine_enabled, False)
        self.gate(True)
        for query in ("?multi_machine=false", "?work_orders_multi_machine_enabled=false"):
            reply = await call("GET", PATH + query, cookie=cookie, extra_headers=(("x-multi-machine", "false"),))
            self.assertEqual(reply.json(), {"multi_machine": True}, query)

    async def test_no_method_other_than_get_exists_and_a_body_changes_nothing(self):
        cookie = await self.cookie("JEFATURA")
        before = self.snapshot()
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            reply = await call(method, PATH, json_body={"multi_machine": True, "work_orders_multi_machine_enabled": True}, cookie=cookie)
            self.assertIn(reply.status, (404, 405), method)
        self.assertIs(settings.work_orders_multi_machine_enabled, False)
        self.assertEqual((await self.get(PATH)).json(), {"multi_machine": False})
        self.assertEqual(self.snapshot(), before)

    async def test_reading_it_writes_nothing(self):
        before = self.snapshot()
        for user in ("JEFATURA", "SUPERVISION", "OPERACION"):
            await self.get(PATH, user)
        self.assertEqual(self.snapshot(), before)


class CompatibilityTests(CapabilitiesCase):
    async def test_creation_publication_and_the_gate_behave_exactly_as_before(self):
        traditional = await self.post("/api/work-orders", wm.order_body([wm.body_line(wm.MP1_CODES[0], pv="PV-1"), wm.body_line(wm.MP1_CODES[1], pv="PV-2")]))
        self.assertEqual(traditional.status, 201, traditional.text)
        published = await self.post(f"/api/work-orders/{traditional.json()['id']}/publish")
        self.assertEqual(published.status, 200)
        refused = await self.post("/api/work-orders", wm.order_body(wm.THREE))
        self.assertEqual((refused.status, refused.json()["code"]), (422, "MULTI_MACHINE_DISABLED"))  # reading the capability did not change the gate
        self.gate(True)
        accepted = await self.post("/api/work-orders", wm.order_body(wm.THREE))
        self.assertEqual(accepted.status, 201, accepted.text)
        self.assertEqual([l["machine"]["code"] for l in accepted.json()["baseline"]["lines"]], ["MP1", "MP1", "MP3"])


if __name__ == "__main__":
    unittest.main()
