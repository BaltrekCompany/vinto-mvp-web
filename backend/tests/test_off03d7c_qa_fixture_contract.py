"""D7C: QA catalog and signer contract (no DB, no secrets stored)."""
import dataclasses
import unittest

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.qa_offline_fixture_contract import (
    QA_FORMS, QA_MACHINES, QA_PROFILE, QA_SECTOR, QaFixtureBlocked,
    validate_qa_bundle, validate_repo_qa_fixture_contract,
)
from app.seed.bundle import load_bundle
from app.offline_scope.signing import (
    SigningKey, encode_b64, sign_scope, sign_quality_package,
    verify_scope, verify_quality_package, SCHEMA, AUDIENCE, ISSUER,
    PACKAGE_SCHEMA, PACKAGE_AUDIENCE,
)


class QaFixtureContractTests(unittest.TestCase):
    def test_reference_bundle_is_valid_and_matches_qa_contract(self):
        info = validate_repo_qa_fixture_contract()
        self.assertEqual(info.profile, QA_PROFILE)
        self.assertEqual(info.sector, QA_SECTOR)
        self.assertEqual(set(info.machines), QA_MACHINES)
        self.assertEqual({x for x, _ in info.form_versions}, QA_FORMS)
        self.assertEqual(len(info.source_checksum), 64)
        self.assertEqual(info.publish_status, "NOT_VERIFIED_IN_QA_DB")
        self.assertEqual(info.effective_grants, "NOT_CREATED")

    def test_missing_profile_blocks(self):
        bundle = load_bundle()
        altered = dataclasses.replace(
            bundle, profiles=tuple(x for x in bundle.profiles if x["code"] != QA_PROFILE)
        )
        with self.assertRaises(QaFixtureBlocked):
            validate_qa_bundle(altered)

    def test_machine_or_form_drift_blocks(self):
        bundle = load_bundle()
        without_mp3 = dataclasses.replace(
            bundle, machines=tuple(x for x in bundle.machines if x["code"] != "MP3")
        )
        with self.assertRaises(QaFixtureBlocked):
            validate_qa_bundle(without_mp3)
        changed_form = tuple(
            {**f, "area": "production"} if f["code"] == "VINTO-P1-18" else f
            for f in bundle.forms
        )
        with self.assertRaises(QaFixtureBlocked):
            validate_qa_bundle(dataclasses.replace(bundle, forms=changed_form))

    def test_candidate_scope_blocks(self):
        bundle = load_bundle()
        changed_manifest = {**bundle.manifest, "scope": {**bundle.manifest["scope"], "candidate": True}}
        with self.assertRaises(QaFixtureBlocked):
            validate_qa_bundle(dataclasses.replace(bundle, manifest=changed_manifest))


class QaSignerContractTests(unittest.TestCase):
    def test_ephemeral_signatures_require_pinned_public_key_and_distinct_domain(self):
        # Key exists only in this CI process memory; never emit or persist seed.
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        import hashlib
        signer = SigningKey(private, encode_b64(public), "ed25519-" + hashlib.sha256(public).hexdigest()[:20])
        scope_payload = {"schema": SCHEMA, "audience": AUDIENCE, "issuer": ISSUER,
                         "kind": "scope_readiness_only", "captures_enabled": False}
        package_payload = {"schema": PACKAGE_SCHEMA, "audience": PACKAGE_AUDIENCE,
                           "issuer": ISSUER, "kind": "quality_definition_readiness_only",
                           "captures_enabled": False}
        scope = sign_scope(scope_payload, signer=signer)
        pkg = sign_quality_package(package_payload, signer=signer)
        self.assertTrue(verify_scope(scope, trusted_public_key_b64url=signer.public_b64url))
        self.assertTrue(verify_quality_package(pkg, trusted_public_key_b64url=signer.public_b64url))
        self.assertFalse(verify_quality_package(scope, trusted_public_key_b64url=signer.public_b64url))
        self.assertFalse(verify_scope(pkg, trusted_public_key_b64url=signer.public_b64url))
        other_pub = Ed25519PrivateKey.generate().public_key().public_bytes(
            Encoding.Raw, PublicFormat.Raw
        )
        self.assertFalse(verify_scope(scope, trusted_public_key_b64url=encode_b64(other_pub)))
        tampered_scope = dict(scope)
        tampered_scope["payload"] = {**scope_payload, "captures_enabled": True}
        self.assertFalse(verify_scope(tampered_scope, trusted_public_key_b64url=signer.public_b64url))


if __name__ == "__main__":
    unittest.main()
