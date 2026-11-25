"""Unit tests for the exact signed envelope contract consumed by the browser."""
import base64
import unittest
import uuid
from datetime import datetime, timezone

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from app.quality.offline_capture_scope import DOMAIN, _canonical, sign_quality_capture_scope

SEED = "42" * 32
USER = "b38e5e52-5e30-4f08-ae9c-644443e6f115"
DEVICE = "7ebee083-730e-4d4d-ac6c-f9ea67fabce5"
GRANT = "59c89829-0a8d-4c84-8e7e-2b6b0d90557e"
SCOPE = {
    "machine_code":"MP1",
    "form_code":"VINTO-P1-19",
    "form_version":4,
    "operation":"quality_bobbin_capture",
    "grant_id":GRANT,
}


class QualityOfflineCaptureScopeTests(unittest.TestCase):
    def test_spec_envelope_verifies_with_pinned_public_key(self):
        envelope = sign_quality_capture_scope(
            signing_seed_hex=SEED, subject_user_id=USER,
            device_key=DEVICE, form_scopes=[SCOPE],
            now=datetime(2026,11,25,tzinfo=timezone.utc),
            snapshot_id="9807c5a8-2552-44fc-a856-e7d816487f87",
        )
        self.assertEqual(envelope["payload"]["kind"], "capture_authority")
        self.assertEqual(envelope["payload"]["audience"], "vinto-offline-operational-capture")
        self.assertEqual(envelope["payload"]["subject_user_id"], USER)
        self.assertEqual(envelope["payload"]["device_key"], DEVICE)
        self.assertEqual(envelope["payload"]["expires_at"], "2026-11-25T12:00:00Z")
        raw_public = base64.urlsafe_b64decode(envelope["public_key_b64url"]+"==")
        signature = base64.urlsafe_b64decode(envelope["signature_b64url"]+"==")
        private=Ed25519PrivateKey.from_private_bytes(bytes.fromhex(SEED))
        self.assertEqual(envelope["key_id"][:8], "ed25519-")
        private.public_key().verify(signature, DOMAIN+_canonical(envelope["payload"]))
        self.assertEqual(len(raw_public), 32)

    def test_rejects_incorrect_operation_duplicated_scope_and_non_uuid_device(self):
        kwargs={"signing_seed_hex":SEED, "subject_user_id":USER,
                "device_key":DEVICE, "form_scopes":[SCOPE]}
        for patch in (
            {"form_scopes":[{**SCOPE,"operation":"quality_machine_capture"}]},
            {"form_scopes":[SCOPE,SCOPE]},
            {"device_key":str(uuid.uuid1())},
            {"form_scopes":[]},
            {"signing_seed_hex":"00"},
        ):
            with self.subTest(patch=patch), self.assertRaises(ValueError):
                sign_quality_capture_scope(**{**kwargs,**patch})

    def test_canonical_signature_does_not_depend_on_dictionary_order(self):
        envelope=sign_quality_capture_scope(
            signing_seed_hex=SEED,subject_user_id=USER,device_key=DEVICE,form_scopes=[SCOPE])
        p=envelope["payload"]
        self.assertEqual(_canonical(p),_canonical(dict(reversed(list(p.items())))))


if __name__=="__main__":
    unittest.main()
