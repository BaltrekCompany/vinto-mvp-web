"""OFF-03D.7C6A code-only QA write guard checks. Does NOT reach QA server."""
import unittest
from pathlib import Path

from app.auth.permissions import CALIDAD, QUALITY_CAPTURE, QUALITY_RELEASE, USER_MANAGE, permissions_for_profiles
from app.qa_offline_guard import (
    QA_ALLOWED_UNSAFE_REQUESTS, SAFE_METHODS, qa_offline_request_permitted,
)


class QaIdentityWriteExposureTests(unittest.TestCase):
    def test_calidad_profile_can_capture_and_release_without_extra_qa_guard(self):
        perms = permissions_for_profiles([CALIDAD])
        self.assertIn(QUALITY_CAPTURE, perms)
        self.assertIn(QUALITY_RELEASE, perms)
        self.assertNotIn(USER_MANAGE, perms)

    def test_all_operational_unsafe_methods_denied_in_qa(self):
        # No session, DB write, or network access needed: pure guard function.
        for method in ("POST", "PATCH", "PUT", "DELETE"):
            for path in (
                "/api/quality/machines/MP1/captures",
                "/api/quality/bobbins/example/captures",
                "/api/quality/releases",
                "/api/captures",
                "/api/bobbins",
                "/api/admin/users",
                "/api/work-orders",
                "/api/assignments",
                "/api/offline/sync",
                "/api/offline/outbox",
                "/api/offline/scope/",
                "/api/offline/quality-package/",
            ):
                with self.subTest(method=method, path=path):
                    self.assertFalse(qa_offline_request_permitted(
                        app_env="qa", method=method, path=path
                    ))

    def test_only_four_exact_post_exceptions_for_readiness_qa(self):
        self.assertEqual(QA_ALLOWED_UNSAFE_REQUESTS, {
            ("POST", "/api/auth/login"),
            ("POST", "/api/auth/logout"),
            ("POST", "/api/offline/scope"),
            ("POST", "/api/offline/quality-package"),
        })
        self.assertEqual(SAFE_METHODS, {"GET", "HEAD", "OPTIONS"})
        for method, path in QA_ALLOWED_UNSAFE_REQUESTS:
            self.assertTrue(qa_offline_request_permitted(
                app_env="qa", method=method, path=path
            ))
            self.assertFalse(qa_offline_request_permitted(
                app_env="qa", method="PATCH", path=path
            ))
        # Existing pilot behavior is unchanged by this QA-specific guard.
        self.assertTrue(qa_offline_request_permitted(
            app_env="production", method="POST",
            path="/api/quality/machines/MP1/captures"
        ))

    def test_actual_asgi_app_wires_the_qa_guard(self):
        root = Path(__file__).resolve().parents[1] / "app"
        source = (root / "main.py").read_text(encoding="utf-8")
        self.assertIn('from app.qa_offline_guard import qa_offline_request_permitted', source)
        self.assertIn('@app.middleware("http")', source)
        self.assertIn('app_env=settings.app_env', source)
        self.assertIn('status_code=403', source)
        self.assertIn('Cache-Control": "no-store"', source)

    def test_cli_identity_fallback_risk_and_role_cut_not_automated(self):
        root = Path(__file__).resolve().parents[1]
        src = (root / "create_user.py").read_text(encoding="utf-8")
        self.assertIn("settings.identity_database_url", src)
        self.assertIn("settings.database_url", src)
        self.assertIn("return psycopg.connect(url.get_secret_value()", src)
        role_sql = (root / "roles" / "03c_d3b2_identity_role_grants.sql").read_text(encoding="utf-8")
        self.assertIn("vinto_identity", role_sql)
        cut = (root / "roles" / "03d_d3b4_cut_identity_dml.sql").read_text(encoding="utf-8")
        self.assertIn("CUT-IDENTITY-DML-APPROVED", cut)


if __name__ == "__main__":
    unittest.main()
