"""E1-05 server capability and Supervisor API access, isolated PostgreSQL 17."""
import unittest
from unittest.mock import patch

from app.config import settings
from app.ephemeral_db import build_reference_template, drop_database
from app.work_orders.router import router

try:
    import test_work_orders_multimachine_api as wm
except ModuleNotFoundError:
    from tests import test_work_orders_multimachine_api as wm

PATH = "/api/work-orders/execution-capabilities"
OLD = "/api/work-orders/capabilities"
call = wm.call


def setUpModule():
    wm.STATE["template"] = build_reference_template("vinto_e105api_tpl")


def tearDownModule():
    if wm.STATE.get("template"):
        drop_database(wm.STATE["template"])
        wm.STATE.pop("template", None)


class ExecutionCapabilitiesApiTests(wm.MultiMachineApiCase):
    async def test_supervisor_sees_independent_flag_off_and_on(self):
        off = await self.get(PATH, "SUPERVISION")
        self.assertEqual((off.status, off.json()), (200, {"line_execution": False}))
        self.assertEqual({k.decode().lower(): v.decode() for k, v in off.headers}["cache-control"], "private, no-store")
        with patch.object(settings, "work_order_line_execution_enabled", True):
            on = await self.get(PATH, "SUPERVISION")
            self.assertEqual((on.status, on.json()), (200, {"line_execution": True}))
        self.assertEqual((await self.get(PATH, "SUPERVISION")).json(), {"line_execution": False})

    async def test_jefatura_operacion_calidad_must_not_read_flag(self):
        for role in ("JEFATURA", "JEFATURA_BOBINAS", "OPERACION", "CALIDAD", "DATA_BALTREK"):
            result = await self.get(PATH, role)
            self.assertEqual(result.status, 403, role)
            self.assertNotIn("line_execution", result.text)

    async def test_invalid_or_missing_session_is_401(self):
        self.assertEqual((await call("GET", PATH)).status, 401)
        self.assertEqual((await call("GET", PATH, cookie="bad")).status, 401)

    async def test_old_capability_response_remains_byte_for_byte_shape_compatible(self):
        for role in ("JEFATURA", "SUPERVISION"):
            self.assertEqual((await self.get(OLD, role)).json(), {"multi_machine": False})
        with patch.object(settings, "work_order_line_execution_enabled", True):
            self.assertEqual((await self.get(OLD, "JEFATURA")).json(), {"multi_machine": False})
            self.assertEqual((await self.get(OLD, "SUPERVISION")).json(), {"multi_machine": False})

    async def test_execution_read_route_requires_supervisor_and_feature(self):
        order_id = "00000000-0000-4000-8000-000000000000"
        endpoint = "/api/work-orders/" + order_id + "/execution"
        self.assertEqual((await self.get(endpoint, "JEFATURA")).status, 403)
        unavailable = await self.get(endpoint, "SUPERVISION")
        self.assertEqual((unavailable.status, unavailable.json()["code"]), (422, "LINE_EXECUTION_DISABLED"))
        with patch.object(settings, "work_order_line_execution_enabled", True):
            missing = await self.get(endpoint, "SUPERVISION")
            self.assertEqual((missing.status, missing.json()["code"]), (404, "WORK_ORDER_NOT_FOUND"))

    async def test_static_paths_before_work_order_dynamic(self):
        paths = [route.path for route in router.routes]
        self.assertLess(paths.index(PATH), paths.index("/api/work-orders/{work_order_id}"))
        self.assertLess(paths.index(OLD), paths.index("/api/work-orders/{work_order_id}"))


if __name__ == "__main__":
    unittest.main()
