"""OFF-03C.1 end-to-end PostgreSQL17 in ephemeral *_test database only.

P1-18/22/26/27 definitions come from published vinto_config rows.
No real operators, OT or VINTO pilot/production database is used.
"""
import hashlib
import unittest
from unittest.mock import patch
from uuid import uuid4
from pydantic import SecretStr

from app.auth.permissions import permissions_for_profiles
from app.auth.service import AuthenticatedUser, create_user
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.offline_scope.service import issue_scope
from app.offline_scope.quality_package import build_quality_package, PackageDenied
from app.offline_scope.signing import (
    encode_b64, canonical_payload, verify_quality_package, load_signer
)

STATE={}
SEED=encode_b64(bytes(range(1,33)))


def setUpModule():
    STATE["template"]=build_reference_template("vinto_off03c1_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class Pg17DefinitionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=copy_database(STATE["template"],"vinto_off03c1")
        cls.addClassCleanup(drop_database,cls.db)
        cls.con=connect(cls.db)
        cls.addClassCleanup(cls.con.close)
        cls.admin=create_user(cls.con,username="offline.package.admin."+uuid4().hex[:7],
                              display_name="CI Admin",profile_code="DATA_BALTREK",
                              password="ci-Only-Disposable-0139!").user_id

    def setUp(self):
        self.created=create_user(self.con,username="offline.package.operator."+uuid4().hex[:7],
                                 display_name="CI Quality",profile_code="CALIDAD",
                                 sectors=("BOBINAS",),password="ci-Only-Disposable-0139!")
        self.user=AuthenticatedUser(self.created.user_id,self.created.username,self.created.display_name,
                                    ("CALIDAD",),permissions_for_profiles(("CALIDAD",)),False,
                                    frozenset({"BOBINAS"}))
        self.device=uuid4()
        with patch.object(settings,"offline_scope_issue_enabled",True),patch.object(
            settings,"offline_scope_signing_seed_b64url",SecretStr(SEED)):
            self.signer=load_signer()

    def grant(self,code):
        grant_machine_form(self.con,user_id=self.user.user_id,machine_code="MP1",
                           form_code=code,actor_id=self.admin)

    def scope(self):
        return issue_scope(self.con,self.user,device_key=self.device,
                           machine_codes=["MP1"],signer=self.signer)

    def package(self,code,scope):
        return build_quality_package(self.con,self.user,device_key=self.device,
            machine_code="MP1",form_code=code,signed_scope=scope,signer=self.signer)

    def test_p1_22_fields_options_and_checksum_match_published_database(self):
        self.grant("VINTO-P1-22")
        package=self.package("VINTO-P1-22",self.scope())
        p=package["payload"]
        self.assertEqual(p["kind"],"quality_definition_readiness_only")
        self.assertFalse(p["captures_enabled"])
        self.assertTrue(verify_quality_package(package,trusted_public_key_b64url=self.signer.public_b64url))
        definition=p["definition"]
        self.assertEqual(definition["form_version"],p["form_version"])
        self.assertEqual(definition["form_code"],"VINTO-P1-22")
        self.assertGreaterEqual(len(definition["fields"]),4)
        self.assertEqual(p["content_sha256"],hashlib.sha256(canonical_payload(definition)).hexdigest())
        self.assertFalse(definition["recipe_bundle_included"])
        self.assertFalse(definition["capture_eligible"])

    def test_p1_26_calculated_backend_rule_and_options_explicit(self):
        self.grant("VINTO-P1-26")
        package=self.package("VINTO-P1-26",self.scope())
        definition=package["payload"]["definition"]
        self.assertIn("porcentaje_cantidad_de_seco",definition["calculated_rules"])
        self.assertEqual(definition["calculated_rules"]["porcentaje_cantidad_de_seco"]["denominator"],"masa_humeda")
        point=next(x for x in definition["fields"] if x["key"]=="punto_de_muestreo")
        self.assertGreaterEqual(len(point["options"]),5)
        self.assertFalse(definition["capture_eligible"])

    def test_revocation_wrong_grant_or_machine_rejects_historical_scope(self):
        self.grant("VINTO-P1-22")
        scope=self.scope()
        revoke_machine_form(self.con,user_id=self.user.user_id,machine_code="MP1",
                            form_code="VINTO-P1-22",actor_id=self.admin)
        with self.assertRaises(PackageDenied):
            self.package("VINTO-P1-22",scope)
        with self.assertRaises(PackageDenied):
            build_quality_package(self.con,self.user,device_key=self.device,machine_code="MP3",
                form_code="VINTO-P1-22",signed_scope=scope,signer=self.signer)
        with self.assertRaises(PackageDenied):
            self.package("VINTO-P1-18",scope)


if __name__ == "__main__":
    unittest.main()
