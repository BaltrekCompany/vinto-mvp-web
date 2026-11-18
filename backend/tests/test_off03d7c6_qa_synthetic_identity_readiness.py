"""OFF-03D.7C6 read-only static readiness tests; no SQL or secret generation."""
import unittest
from pathlib import Path

from app.auth.permissions import (
    CALIDAD, QUALITY_CAPTURE, QUALITY_RELEASE, USER_MANAGE, CATALOG_MANAGE,
    permissions_for_profiles,
)
from app.authz.policies import Operation, policy_for
from app.config import Settings
from app.qa_offline_fixture_contract import (
    QA_FORMS, QA_MACHINES, QA_PROFILE, QA_SECTOR, QA_USERNAME,
    validate_repo_qa_fixture_contract,
)


class QaSyntheticReadinessTests(unittest.TestCase):
    def test_canonical_qa_contract_eight_exact_pairs(self):
        contract = validate_repo_qa_fixture_contract()
        self.assertEqual(QA_USERNAME, "qa.offline.calidad")
        self.assertEqual(QA_PROFILE, CALIDAD)
        self.assertEqual(QA_SECTOR, "BOBINAS")
        self.assertEqual(contract.user, QA_USERNAME)
        self.assertEqual(contract.profile, QA_PROFILE)
        self.assertEqual(contract.sector, QA_SECTOR)
        self.assertEqual(QA_MACHINES, {"MP1", "MP3"})
        self.assertEqual(QA_FORMS, {"VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27"})
        pairs = {(m, f) for m in QA_MACHINES for f in QA_FORMS}
        self.assertEqual(len(pairs), 8)
        self.assertEqual({c for c, v in contract.form_versions},
                         QA_FORMS)
        self.assertEqual({v for c, v in contract.form_versions if c == "VINTO-P1-26"}, {3})
        self.assertEqual(contract.effective_grants, "NOT_CREATED")

    def test_calidad_also_grants_write_capabilities_not_read_only(self):
        perms = permissions_for_profiles([CALIDAD])
        self.assertIn(QUALITY_CAPTURE, perms)
        self.assertIn(QUALITY_RELEASE, perms)
        self.assertNotIn(USER_MANAGE, perms)
        self.assertNotIn(CATALOG_MANAGE, perms)
        self.assertEqual(policy_for(Operation.QUALITY_MACHINE_CAPTURE).permission, QUALITY_CAPTURE)
        self.assertTrue(QA_FORMS <= policy_for(Operation.QUALITY_MACHINE_CAPTURE).admitted())

    def test_offline_signing_flags_disabled_are_not_capture_guard(self):
        fields = Settings.model_fields
        self.assertIs(fields["offline_scope_issue_enabled"].default, False)
        self.assertIs(fields["offline_quality_package_issue_enabled"].default, False)
        self.assertEqual(fields["authz_quality_machine_captures_mode"].default, "off")
        self.assertEqual(fields["authz_quality_bobbin_captures_mode"].default, "off")

    def test_identity_cli_can_fallback_without_dedicated_url(self):
        source = (Path(__file__).resolve().parents[1] / "create_user.py").read_text(encoding="utf-8")
        self.assertIn("settings.identity_database_url", source)
        self.assertIn("settings.database_url", source)
        self.assertIn("--password-env", source)
        self.assertIn("create_user(connection", source)
        self.assertIn("--sector", source)

    def test_no_offline_qa_identity_created_from_this_module(self):
        from app import qa_offline_fixture_contract as c
        source = Path(c.__file__).read_text(encoding="utf-8")
        self.assertNotIn("psycopg.connect", source)
        self.assertNotIn("INSERT INTO ", source)
        self.assertNotIn("CREATE ROLE ", source)


if __name__ == "__main__":
    unittest.main()
