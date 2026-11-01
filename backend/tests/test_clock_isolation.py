"""QA-REG.1: aislamiento del reloj de pruebas (`capture_service._now`).

Las pruebas `test_concurrency_identical_posts_create_one_capture` de DEV-B1 y DEV-B2 lanzaban cinco peticiones con `asyncio.gather`, y cada una abría su PROPIO `patch.object(capture_service, "_now")`.
Los parches superpuestos salen fuera de orden LIFO y uno de ellos «restaura» un mock en lugar de la función original: `_now` quedaba fijado para el resto de la ejecución y toda prueba posterior que
activaba una asignación con el reloj real recibía 409 ASSIGNMENT_STALE (dependiente del orden de `unittest discover`). Aquí se demuestra el mecanismo, que la forma corregida (UN parche para todo el lote)
restaura exactamente `_now`, que las dos pruebas reales ya no lo filtran y qué efecto tenía sobre una captura F3 posterior. No se relaja ASSIGNMENT_STALE ni se limpia nada «entre pruebas».
"""

import asyncio
import importlib.util
import io
import unittest
from unittest.mock import patch
from uuid import uuid4

from app import capture_service as cs
from app.ephemeral_db import build_reference_template, drop_database

try:
    import test_f3_bobbins_api as f3
    from test_assignments_api import call
except ModuleNotFoundError:
    import tests.test_f3_bobbins_api as f3
    from tests.test_assignments_api import call

ORIGINAL_NOW = cs._now  # capturado al importar este módulo
CONCURRENCY_TESTS = (
    "test_devb1_p105_p131.WriteTests.test_concurrency_identical_posts_create_one_capture",
    "test_devb2_p104.WriteTests.test_concurrency_identical_posts_create_one_capture",
)
STATE = {}


def setUpModule():
    STATE["template"] = build_reference_template("vinto_clock_tpl")
    f3.STATE["template"] = STATE["template"]


def tearDownModule():
    drop_database(STATE["template"])


def fixed_clock(value):
    return patch.object(cs, "_now", return_value=value)


def run_real_tests(*names):
    """Ejecuta las pruebas reales (con sus fixtures de módulo) y devuelve el resultado."""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for name in names:
        prefix = "" if importlib.util.find_spec(name.split(".")[0]) else "tests."  # `python -m unittest tests.x` y `discover -s tests` importan los módulos con nombres distintos
        suite.addTests(loader.loadTestsFromName(prefix + name))
    return unittest.TextTestRunner(stream=io.StringIO(), verbosity=0).run(suite)


class ClockGuard:
    """Cada prueba de este módulo comprueba al terminar que `_now` es EXACTAMENTE el original (y lo restaura si no, para no contaminar a las demás)."""

    def _guard(self):
        def check():
            leaked = cs._now is not ORIGINAL_NOW
            cs._now = ORIGINAL_NOW
            self.assertFalse(leaked, "capture_service._now quedó parcheado al terminar la prueba")
        self.addCleanup(check)


# ---- 1. el mecanismo, sin base de datos ---------------------------------------------------------------------------------------------------------------

class MechanismTests(ClockGuard, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self._guard()

    async def test_the_previous_pattern_could_leave_a_mock_active(self):
        """Cinco tareas, cada una con su propio patch.object, que salen en orden de entrada (como las peticiones concurrentes): la última restaura un mock."""
        async def old_style_post(index):
            with patch.object(cs, "_now", return_value=index):
                await asyncio.sleep(0.01 * (index + 1))  # sale la tarea 0 primero, luego la 1...: no es LIFO
        await asyncio.gather(*[old_style_post(i) for i in range(5)])
        leaked = cs._now
        cs._now = ORIGINAL_NOW  # esta prueba contamina A PROPÓSITO y limpia lo suyo antes de terminar
        self.assertIsNot(leaked, ORIGINAL_NOW)  # el reloj quedó fijado: la fuga que provocaba ASSIGNMENT_STALE
        self.assertTrue(isinstance(leaked, unittest.mock.MagicMock))

    async def test_one_patch_around_the_whole_batch_restores_the_original_exactly(self):
        async def request(index):
            await asyncio.sleep(0.01 * (5 - index))  # orden de salida distinto: da igual, el parche es uno
            return cs._now(None)
        with fixed_clock("fijo"):
            replies = await asyncio.gather(*[request(i) for i in range(5)])
        self.assertEqual(replies, ["fijo"] * 5)  # las cinco peticiones vieron el reloj fijado y siguen siendo concurrentes
        self.assertIs(cs._now, ORIGINAL_NOW)

    async def test_the_single_patch_is_restored_after_an_exception_or_a_cancellation(self):
        async def failing():
            raise RuntimeError("respuesta inesperada")

        async def slow():
            await asyncio.sleep(5)
        with self.assertRaises(RuntimeError):
            with fixed_clock("fijo"):
                await asyncio.gather(failing(), slow())
        self.assertIs(cs._now, ORIGINAL_NOW)
        with self.assertRaises(asyncio.TimeoutError):
            with fixed_clock("fijo"):
                await asyncio.wait_for(asyncio.gather(slow(), slow()), timeout=0.05)
        self.assertIs(cs._now, ORIGINAL_NOW)
        with fixed_clock("fijo"):
            tasks = [asyncio.ensure_future(slow()) for _ in range(3)]
            await asyncio.sleep(0.01)
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        self.assertIs(cs._now, ORIGINAL_NOW)


# ---- 2. las pruebas reales ya no filtran el reloj; efecto sobre una captura F3 posterior ---------------------------------------------------------------

class RealConcurrencyTestsTests(ClockGuard, f3.BobbinApiCase):
    async def asyncSetUp(self):
        await super().asyncSetUp()
        self._guard()

    async def test_the_two_real_concurrency_tests_pass_and_restore_the_clock_exactly(self):
        result = await asyncio.to_thread(run_real_tests, *CONCURRENCY_TESTS)  # en un hilo: no se anida un bucle de eventos dentro de otro
        self.assertEqual((result.testsRun, result.wasSuccessful()), (2, True), [r[1] for r in result.failures + result.errors])
        self.assertIs(cs._now, ORIGINAL_NOW)  # la identidad exacta, sin limpieza posterior

    async def test_a_f3_capture_after_the_concurrency_tests_is_not_stale(self):
        await asyncio.to_thread(run_real_tests, *CONCURRENCY_TESTS)
        _, assignment = await self.assignment()  # la asignación se activa con el reloj REAL
        reply = await self.post(self.payload(assignment))  # y la captura se evalúa con el reloj real: 201, no 409
        self.assertEqual(reply.status, 201, reply.body)

    async def test_the_impact_of_the_old_leak_was_a_409_assignment_stale_and_the_check_is_unchanged(self):
        """Reproduce el efecto: con `_now` fijado en otra fecha (lo que dejaba la fuga) una captura F3 con asignación recién activada da 409 ASSIGNMENT_STALE. La comprobación NO se relaja."""
        _, assignment = await self.assignment()
        from datetime import datetime, timezone
        with fixed_clock(datetime(2026, 10, 6, 16, 0, tzinfo=timezone.utc)):
            stale = await self.post(self.payload(assignment))
        self.assertEqual(stale.status, 409)
        self.assertIn("ASSIGNMENT_STALE", stale.body.decode())
        ok = await self.post(self.payload(assignment))  # restaurado el reloj real: la misma asignación vale
        self.assertEqual(ok.status, 201, ok.body)


if __name__ == "__main__":
    unittest.main()
