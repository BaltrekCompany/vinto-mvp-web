"""OFF-03D.7C6C1: verify actual FastAPI QA middleware and dedicated identity code in CI.

Uses mocks, no database or network, and does NOT stand in for a deployed QA API.
"""
import asyncio
import unittest
from unittest.mock import patch, sentinel

import psycopg
from fastapi.routing import APIRoute
from pydantic import SecretStr
from starlette.requests import Request
from starlette.responses import Response

from app import database
from app.config import settings
from app.main import app, qa_offline_write_guard


def make_request(method: str, path: str) -> Request:
    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("utf-8"),
        "query_string": b"",
        "headers": [],
        "client": ("127.0.0.1", 12345),
        "server": ("127.0.0.1", 0),
    }
    return Request(scope)


class QaApiCodeReadinessTests(unittest.TestCase):
    def test_real_asgi_qa_guard_blocks_operational_writes_before_handler(self):
        async def forbidden_handler(_request):
            raise AssertionError("QA operational write reached downstream handler")

        paths = (
            "/api/quality/machines/MP1/captures",
            "/api/quality/bobbins/synthetic/captures",
            "/api/admin/users",
            "/api/captures",
            "/api/bobbins",
            "/api/assignments",
            "/api/work-orders",
            "/api/offline/sync",
            "/api/offline/scope/",
            "/api/offline/quality-package/",
        )
        with patch.object(settings, "app_env", "qa"):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                for path in paths:
                    with self.subTest(method=method, path=path):
                        response = asyncio.run(qa_offline_write_guard(
                            make_request(method, path), forbidden_handler,
                        ))
                        self.assertEqual(response.status_code, 403)
                        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_only_exact_qa_posts_for_authentication_and_signed_readonly_packages(self):
        async def handler(_request):
            return Response(status_code=204)
        for path in (
            "/api/auth/login",
            "/api/auth/logout",
            "/api/offline/scope",
            "/api/offline/quality-package",
        ):
            with patch.object(settings, "app_env", "qa"):
                response = asyncio.run(qa_offline_write_guard(
                    make_request("POST", path), handler,
                ))
            self.assertEqual(response.status_code, 204, path)
        with patch.object(settings, "app_env", "qa"):
            response = asyncio.run(qa_offline_write_guard(
                make_request("GET", "/api/quality/machines/MP1/captures"), handler,
            ))
        self.assertEqual(response.status_code, 204)

    def test_http_routes_are_wired_to_dedicated_identity_dependency(self):
        urls = [
            ("/api/auth/login", "POST"),
            ("/api/admin/users", "GET"),
            ("/api/admin/users", "POST"),
            ("/api/admin/users/{user_id}/grants/grant", "POST"),
        ]
        for path, method in urls:
            with self.subTest(path=path, method=method):
                matches = [
                    route for route in app.routes
                    if isinstance(route, APIRoute)
                    and route.path == path
                    and method in route.methods
                ]
                self.assertEqual(len(matches), 1, f"available routes: {[(type(r).__name__, getattr(r, 'path', None), getattr(r, 'methods', None)) for r in app.routes][:40]}")
                deps = matches[0].dependant.dependencies
                self.assertTrue(
                    any(d.call is database.get_identity_connection for d in deps),
                    f"{method} {path} must use get_identity_connection",
                )

    def test_identity_connection_uses_dedicated_url_and_never_falls_back_on_error(self):
        business = SecretStr("postgresql://vinto_app:fake@127.0.0.1:6554/vinto_qa_offline")
        dedicated = SecretStr("postgresql://vinto_identity:fake@127.0.0.1:6554/vinto_qa_offline")
        with patch.object(settings, "database_url", business), patch.object(settings, "identity_database_url", dedicated):
            self.assertEqual(database.identity_connection_mode(), "dedicated")
            with patch.object(database.psycopg, "connect", return_value=sentinel.dedicated_connection) as pg_connect:
                result = database.open_identity_connection()
                self.assertIs(result, sentinel.dedicated_connection)
                self.assertEqual(pg_connect.call_count, 1)
                self.assertEqual(pg_connect.call_args.args[0], dedicated.get_secret_value())
                self.assertNotEqual(pg_connect.call_args.args[0], business.get_secret_value())
            with patch.object(database.psycopg, "connect", side_effect=psycopg.OperationalError) as pg_connect:
                with self.assertRaises(database.DatabaseUnavailable):
                    database.open_identity_connection()
                self.assertEqual(pg_connect.call_count, 1)
                self.assertEqual(pg_connect.call_args.args[0], dedicated.get_secret_value())

    def test_environment_defaults_are_not_mistaken_for_deployment_proof(self):
        with patch.object(settings, "app_env", "qa"), patch.object(settings, "pg_privilege_mode", "hardened"):
            self.assertEqual(settings.app_env, "qa")
            self.assertEqual(settings.pg_privilege_mode, "hardened")
        # This is only local function-level evidence. QA API deployment,
        # hostname allowlist, runtime env values and two-role D3B3 flows
        # remain pending external verification.
