"""Contrato HTTP y CORS sin escribir datos de negocio."""

import json
import unittest
from unittest.mock import patch

from app.database import DatabaseUnavailable
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
    async def test_zero_is_a_success(self):
        with patch("app.captures.count_captures", return_value=0):
            status, _, body = await request("/api/captures/count", "front=Bobinas")
        self.assertEqual(status, 200)
        self.assertEqual(body, {"front": "Bobinas", "count": 0, "source": "database"})

    async def test_all_existing_fronts_and_positive_count(self):
        from urllib.parse import urlencode
        for front in ("Bobinas", "Rebobinado", "Conversión", "Calidad"):
            with self.subTest(front=front), patch("app.captures.count_captures", return_value=3) as count:
                status, _, body = await request("/api/captures/count", urlencode({"front": front}))
                self.assertEqual(status, 200)
                self.assertEqual(body["count"], 3)
                count.assert_called_once_with(front)

    async def test_invalid_or_missing_front_does_not_query_database(self):
        for query in ("", "front=Inventado"):
            with patch("app.captures.count_captures") as count:
                status, _, _ = await request("/api/captures/count", query)
                self.assertEqual(status, 422)
                count.assert_not_called()

    async def test_database_failure_is_safe_and_has_cors(self):
        with patch("app.captures.count_captures", side_effect=DatabaseUnavailable("private detail")):
            status, headers, body = await request("/api/captures/count", "front=Bobinas", "http://127.0.0.1:8787")
        self.assertEqual(status, 503)
        self.assertEqual(body, {"status": "error", "database": "unavailable"})
        self.assertEqual(headers[b"access-control-allow-origin"], b"http://127.0.0.1:8787")

    async def test_other_origins_are_not_authorized(self):
        with patch("app.captures.count_captures", return_value=0):
            _, headers, _ = await request("/api/captures/count", "front=Bobinas", "http://example.com")
        self.assertNotIn(b"access-control-allow-origin", headers)

    async def test_health_does_not_query_database(self):
        with patch("app.main.check_database") as check:
            status, _, body = await request("/health")
        self.assertEqual((status, body), (200, {"status": "ok"}))
        check.assert_not_called()

    async def test_real_connection_failure_returns_503(self):
        from psycopg.conninfo import make_conninfo
        from pydantic import SecretStr
        from app.config import settings
        closed_port_url = SecretStr(make_conninfo(settings.database_url.get_secret_value(), host="127.0.0.1", port=1))
        with patch.object(settings, "database_url", closed_port_url):
            status, _, body = await request("/api/captures/count", "front=Bobinas")
        self.assertEqual((status, body), (503, {"status": "error", "database": "unavailable"}))


class CaptureQueryTests(unittest.TestCase):
    def test_real_counts_filter_sector_and_quality_without_persisting_fixtures(self):
        # Reuse existing fixtures, all inside the same rolled-back transaction.
        from test_schema import SchemaTests
        fixture = SchemaTests()
        self.addCleanup(fixture.doCleanups)
        fixture.setUp()
        connection = fixture.connection
        baseline = {front: connection.execute(*capture_count_query(front)).fetchone()[0]
                    for front in ("Bobinas", "Rebobinado", "Conversión", "Calidad")}
        connection.execute("UPDATE vinto_master.sector SET name='Bobinas' WHERE id=%s", (fixture.sector,))
        fixture.capture()
        fixture.capture()
        self.assertEqual(connection.execute(*capture_count_query("Bobinas")).fetchone()[0], baseline["Bobinas"] + 2)
        for front in ("Rebobinado", "Conversión", "Calidad"):
            self.assertEqual(connection.execute(*capture_count_query(front)).fetchone()[0], baseline[front])
        version = fixture.insert("vinto_config.form_version",
            "form_id,version_number,name,area,workflow_id,definition_checksum",
            (fixture.form, 2, "Technical quality fixture", "quality", fixture.workflow, "2" * 64))
        connection.execute("INSERT INTO vinto_config.form_version_machine (form_version_id,machine_id) VALUES (%s,%s)", (version, fixture.machine))
        connection.execute("UPDATE vinto_config.form_version SET status='published',published_at=clock_timestamp() WHERE id=%s", (version,))
        fixture.capture(form_version_id=version)
        self.assertEqual(connection.execute(*capture_count_query("Calidad")).fetchone()[0], baseline["Calidad"] + 1)
        self.assertEqual(connection.execute(*capture_count_query("Bobinas")).fetchone()[0], baseline["Bobinas"] + 3)
