"""OFF-03C.1 signed definitions: domain separation, integrity, gates, policy.

Pure unit tests with disposable signing seed. No industrial data or DB writes.
"""
import copy
import unittest
from unittest.mock import patch
from uuid import uuid4
from pydantic import SecretStr

from app.config import settings
from app.offline_scope.signing import (
    PACKAGE_SCHEMA, PACKAGE_AUDIENCE, OfflineSigningUnavailable, load_signer,
    sign_quality_package, verify_quality_package, sign_scope, encode_b64,
    SCHEMA, AUDIENCE, ISSUER
)
from app.offline_scope.quality_package import PackageDenied, _quality_scope

SEED=encode_b64(bytes(range(1,33)))


def signer():
    with patch.object(settings,"offline_scope_issue_enabled",True), patch.object(
        settings,"offline_scope_signing_seed_b64url",SecretStr(SEED)):
        return load_signer()


class QualityPackageCryptoTest(unittest.TestCase):
    def payload(self):
        return {
            "schema":PACKAGE_SCHEMA, "issuer":ISSUER,"audience":PACKAGE_AUDIENCE,
            "kind":"quality_definition_readiness_only","captures_enabled":False,
            "package_id":str(uuid4()),"scope_snapshot_id":str(uuid4()),
            "subject_user_id":str(uuid4()),"device_key":str(uuid4()),
            "machine_code":"MP1","form_code":"VINTO-P1-22","form_version":2,
            "grant_id":str(uuid4()),"issued_at":"2026-11-17T10:00:00Z",
            "content_sha256":"a"*64,
            "definition":{"fields":[{"key":"grado_de_refinacion_sr","required":True}]}
        }

    def test_ed25519_and_exact_external_pin(self):
        key=signer()
        envelope=sign_quality_package(self.payload(),signer=key)
        self.assertTrue(verify_quality_package(envelope,trusted_public_key_b64url=key.public_b64url))
        self.assertFalse(verify_quality_package(envelope,trusted_public_key_b64url=encode_b64(bytes(32))))
        self.assertNotIn(SEED,str(envelope))

    def test_mutated_field_version_and_capture_flag_are_rejected(self):
        key=signer()
        envelope=sign_quality_package(self.payload(),signer=key)
        for mutation in ({"form_version":999},{"captures_enabled":True},
                         {"machine_code":"MP3"},{"definition":{"fields":[]}},
                         {"subject_user_id":str(uuid4())},{"content_sha256":"0"*64}):
            with self.subTest(mutation=mutation):
                changed=copy.deepcopy(envelope)
                changed["payload"].update(mutation)
                self.assertFalse(verify_quality_package(changed,trusted_public_key_b64url=key.public_b64url))

    def test_scope_signature_not_usable_as_package_signature(self):
        key=signer()
        payload={"schema":SCHEMA,"issuer":ISSUER,"audience":AUDIENCE}
        original=sign_scope(payload,signer=key)
        self.assertFalse(verify_quality_package(original,trusted_public_key_b64url=key.public_b64url))
        with self.assertRaises(ValueError):
            sign_quality_package(payload,signer=key)

    def test_bare_scope_wrong_purpose_and_other_actor_denied(self):
        from app.auth.permissions import permissions_for_profiles
        from app.auth.service import AuthenticatedUser
        principal=AuthenticatedUser(uuid4(),"quality.synthetic","Synthetic",("CALIDAD",),
            permissions_for_profiles(("CALIDAD",)),False,frozenset({"BOBINAS"}))
        machine="MP1"; form="VINTO-P1-22"; device=uuid4()
        scope={
            "schema":SCHEMA,"issuer":ISSUER,"audience":AUDIENCE,
            "snapshot_id":str(uuid4()),"subject_user_id":str(principal.user_id),
            "device_key":str(device),"issued_at":"2026-11-17T10:00:00Z",
            "kind":"scope_readiness_only","captures_enabled":False,
            "form_scopes":[{"machine_code":machine,"form_code":form,"form_version":2,
                            "grant_id":str(uuid4()),"operation":"quality_machine_capture"}]
        }
        signed=sign_scope(scope,signer=signer())
        result=_quality_scope(signed,signer(),principal,device,machine,form)
        self.assertEqual(result["scope"]["form_version"],2)
        for altered in [
            (signed,uuid4(),machine,form),
            (signed,device,"MP3",form),
            (signed,device,machine,"VINTO-P1-18")
        ]:
            with self.assertRaises(PackageDenied):
                _quality_scope(altered[0],signer(),principal,*altered[1:])
        tampered=copy.deepcopy(signed)
        tampered["payload"]["captures_enabled"]=True
        with self.assertRaises(PackageDenied):
            _quality_scope(tampered,signer(),principal,device,machine,form)

    def test_flags_are_separate_and_off_by_default(self):
        self.assertFalse(settings.offline_quality_package_issue_enabled)
        with patch.object(settings,"offline_scope_issue_enabled",False),patch.object(
            settings,"offline_scope_signing_seed_b64url",SecretStr(SEED)):
            with self.assertRaises(OfflineSigningUnavailable):
                load_signer()


if __name__ == "__main__":
    unittest.main()
