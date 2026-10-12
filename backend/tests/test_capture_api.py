"""Contrato HTTP y CORS sin escribir datos de negocio.

El endpoint GET /api/captures/count (sesión + catalog.read + alcance por sector) se prueba de extremo a extremo en
tests/test_capture_count_authorization.py. Aquí quedan la salud de la API y la consulta de conteo sobre datos de fixture revertidos.
"""

import json
import unittest
from unittest.mock import patch

from app.main import app
from app.captures import capture_count_query


async def request(path, query="", origin=None):
    messages = []
    headers = [] if origin is None else [(b"origin", origin.encode())]
    scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
             "method": "GET", "scheme": "http", "path": path, "raw_path": path.encode(),
             "query_string": query.encode(), "headers": headers,
             "server": ("127.0.0.1", 8000), "client": ("127.0.0.1", 1234), "root_path": ""}

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    await app(scope, receive, send)
    start = next(m for m in messages if m["type"] == "http.response.start")
    body = b"".join(m.get("body", b"") for m in messages if m["type"] == "http.response.body")
    return start["status"], dict(start["headers"]), json.loads(body)


class CaptureApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_the_count_is_no_longer_public(self):
        # Without a session the request never reaches the count: 401 (or the safe 503 when PostgreSQL is not reachable, because the session is resolved first).
        status, _, body = await request("/api/captures/count", "front=Bobinas")
        self.assertIn(status, (401, 503))
        self.assertNotIn("count", body)

    async def test_health_does_not_query_database(self):
        with patch("app.main.check_database") as check:
            status, _, body = await request("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))
        check.assert_not_called()


class CaptureQueryTests(unittest.TestCase):
    def test_real_counts_filter_sector_code_and_quality_without_persisting_fixtures(self):
        # Reuse existing fixtures, all inside the same rolled-back transaction.
        from test_schema import SchemaTests
        fixture = SchemaTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        connection = fixture.connection
        scope = ("BOBINAS", "REBOBINADO", "CONVERSION")  # full operational scope is intersected with the operational sectors, so it still means BOBINAS only
        count = lambda front, sectors=scope: connection.execute(*capture_count_query(front, sectors)).fetchone()[0]
        baseline = {front: count(front) for front in ("Bobinas", "Rebobinado", "Conversión", "Calidad")}
        connection.execute("UPDATE vinto_master.sector SET code='BOBINAS' WHERE id=%s", (fixture.sector,))  # the fixture sector stands for BOBINAS
        fixture.capture()
        fixture.capture()
        self.assertEqual(count("Bobinas"), baseline["Bobinas"] + 2)
        for front in ("Rebobinado", "Conversión", "Calidad"):
            self.assertEqual(count(front), baseline[front])
        self.assertEqual(count("Bobinas", ()), 0, "an empty scope counts nothing")
        self.assertEqual(count("Bobinas", ("REBOBINADO",)), 0, "a sector the user does not hold counts nothing")
        version = fixture.insert("vinto_config.form_version",
            "form_id,version_number,name,area,workflow_id,definition_checksum",
            (fixture.form, 2, "Technical quality fixture", "quality", fixture.workflow, "2" * 64))
        connection.execute("INSERT INTO vinto_config.form_version_machine (form_version_id,machine_id) VALUES (%s,%s)", (version, fixture.machine))
        connection.execute("UPDATE vinto_config.form_version SET status='published',published_at=clock_timestamp() WHERE id=%s", (version,))
        fixture.capture(form_version_id=version)
        self.assertEqual(count("Calidad"), baseline["Calidad"] + 1)
        self.assertEqual(count("Bobinas"), baseline["Bobinas"] + 3)
        self.assertEqual(count("Calidad", ()), 0, "Calidad is filtered by sector too")
        self.assertEqual(count("Calidad", ("REBOBINADO",)), 0)
