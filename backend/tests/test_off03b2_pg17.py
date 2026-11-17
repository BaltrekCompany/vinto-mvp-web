"""OFF-03B.2 isolated PostgreSQL17: effective grant/signature and real revocation.

Requires TEST_DATABASE_URL/TEST_ADMIN_DATABASE_URL pointing to ephemeral *_test.
Never touches VINTO production or modifies user assignments.
"""
import unittest
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app.auth.permissions import permissions_for_profiles
from app.auth.service import AuthenticatedUser, create_user
from app.auth.machine_form_grants import grant_machine_form, revoke_machine_form
from app.config import settings
from app.ephemeral_db import build_reference_template, connect, copy_database, drop_database
from app.offline_scope.service import OfflineScopeDenied, issue_scope
from app.offline_scope.signing import encode_b64, load_signer, verify_scope

STATE = {}
DEMO_SEED = encode_b64(bytes(range(1,33)))


def setUpModule():
    STATE["template"] = build_reference_template("vinto_off03b2_tpl")


def tearDownModule():
    if STATE.get("template"):
        drop_database(STATE["template"])


class Pg17ScopeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db=copy_database(STATE["template"],"vinto_off03b2")
        cls.addClassCleanup(drop_database,cls.db)
        cls.connection=connect(cls.db)
        cls.addClassCleanup(cls.connection.close)
        cls.admin=create_user(cls.connection,username=f"offline.admin.{uuid4().hex[:7]}",
                              display_name="Offline CI Admin",profile_code="DATA_BALTREK",
                              password="ci-Passphrase-Only-8839!!").user_id

    def setUp(self):
        self.created=create_user(self.connection,username=f"offline.operator.{uuid4().hex[:7]}",
                                display_name="Offline CI Operator",profile_code="OPERACION",
                                password="ci-Passphrase-Only-8839!!",sectors=("BOBINAS",))
        self.user=AuthenticatedUser(self.created.user_id,self.created.username,self.created.display_name,
                                    ("OPERACION",),permissions_for_profiles(("OPERACION",)),False,
                                    frozenset({"BOBINAS"}))
        self.device=uuid4()
        with patch.object(settings,"offline_scope_issue_enabled",True),patch.object(
                settings,"offline_scope_signing_seed_b64url",SecretStr(DEMO_SEED)):
            self.signer=load_signer()

    def sign(self):
        return issue_scope(self.connection,self.user,device_key=self.device,machine_codes=["MP1"],signer=self.signer)

    def test_real_active_grant_required_and_revocation_blocks_reissue(self):
        with self.assertRaises(OfflineScopeDenied):
            self.sign()
        grant_machine_form(self.connection,user_id=self.user.user_id,machine_code="MP1",
                           form_code="VINTO-P1-01",actor_id=self.admin)
        envelope=self.sign()
        self.assertEqual(envelope["payload"]["form_scopes"][0]["form_code"],"VINTO-P1-01")
        self.assertEqual(envelope["payload"]["form_scopes"][0]["machine_code"],"MP1")
        self.assertTrue(verify_scope(envelope,trusted_public_key_b64url=self.signer.public_b64url))
        revoke_machine_form(self.connection,user_id=self.user.user_id,machine_code="MP1",
                            form_code="VINTO-P1-01",actor_id=self.admin)
        with self.assertRaises(OfflineScopeDenied):
            self.sign()
        # Historical signed data is intentionally still verifiable: not a live
        # authorization or permission to sync a capture after revocation.
        self.assertTrue(verify_scope(envelope,trusted_public_key_b64url=self.signer.public_b64url))

    def test_machine_scope_is_exact_and_no_implicit_other_machine(self):
        grant_machine_form(self.connection,user_id=self.user.user_id,machine_code="MP1",
                           form_code="VINTO-P1-01",actor_id=self.admin)
        env=self.sign()
        self.assertTrue(all(x["machine_code"]=="MP1" for x in env["payload"]["form_scopes"]))
        with self.assertRaises(OfflineScopeDenied):
            issue_scope(self.connection,self.user,device_key=self.device,
                        machine_codes=["MP3"],signer=self.signer)

    def test_inactive_user_is_denied_even_with_signed_central_grant(self):
        grant_machine_form(self.connection,user_id=self.user.user_id,machine_code="MP1",
                           form_code="VINTO-P1-01",actor_id=self.admin)
        self.connection.execute('UPDATE vinto_master."user" SET active=false WHERE id=%s',(self.user.user_id,))
        with self.assertRaises(OfflineScopeDenied):
            self.sign()


if __name__ == "__main__":
    unittest.main()
