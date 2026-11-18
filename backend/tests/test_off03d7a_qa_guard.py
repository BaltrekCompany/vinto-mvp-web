"""OFF-03D.7A — QA-only central write deny; no DB needed."""
import asyncio
import unittest

from fastapi.responses import PlainTextResponse
from starlette.requests import Request

from app.config import settings
from app.main import qa_offline_write_guard
from app.qa_offline_guard import qa_offline_request_permitted


class QaOfflineWriteGuardTests(unittest.TestCase):
    def test_qa_allows_only_four_exact_post_endpoints(self):
        allowed = {
            "/api/auth/login", "/api/auth/logout",
            "/api/offline/scope", "/api/offline/quality-package",
        }
        for path in allowed:
            with self.subTest(path=path):
                self.assertTrue(qa_offline_request_permitted(
                    app_env="qa", method="POST", path=path,
                ))
        for path in (
            "/api/captures",
            "/api/bobbins",
            "/api/quality/machines/MP1/captures",
            "/api/quality/bobbins/123/captures",
            "/api/admin/users",
            "/api/work-orders",
            "/api/offline/captures",
            "/api/offline/sync",
            "/api/offline/scope/",
            "/api/offline/scope%2F",
            "/api/auth/login/",
            "/api/auth/reset-password",
            "/api/auth/refresh",
            "/api/test/future-write-endpoint",
        ):
            for method in ("POST", "PUT", "PATCH", "DELETE"):
                with self.subTest(method=method, path=path):
                    self.assertFalse(qa_offline_request_permitted(
                        app_env="qa", method=method, path=path,
                    ))

    def test_qa_allows_safe_read_requests_only(self):
        for method in ("GET", "HEAD", "OPTIONS"):
            self.assertTrue(qa_offline_request_permitted(
                app_env="qa", method=method, path="/api/health",
            ))
        self.assertFalse(qa_offline_request_permitted(
            app_env="qa", method="TRACE", path="/api/health",
        ))

    def test_nonqa_preserves_existing_behavior(self):
        for env in ("local", "ci", "test", "prod", "production"):
            self.assertTrue(qa_offline_request_permitted(
                app_env=env, method="POST", path="/api/captures",
            ))

    def test_actual_fastapi_middleware_denies_before_dispatch(self):
        old = settings.app_env
        settings.app_env = "qa"
        calls = []

        async def handler(_request):
            calls.append("called")
            return PlainTextResponse("downstream", status_code=218)

        def request(path, method):
            return Request({
                "type": "http",
                "method": method,
                "path": path,
                "root_path": "",
                "headers": [],
                "query_string": b"",
                "scheme": "https",
                "server": ("qa.example.invalid", 443),
            })

        try:
            response = asyncio.run(qa_offline_write_guard(
                request("/api/captures", "POST"), handler,
            ))
            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertEqual(calls, [])

            response = asyncio.run(qa_offline_write_guard(
                request("/api/offline/scope", "POST"), handler,
            ))
            self.assertEqual(response.status_code, 218)
            self.assertEqual(calls, ["called"])
        finally:
            settings.app_env = old


if __name__ == "__main__":
    unittest.main()
