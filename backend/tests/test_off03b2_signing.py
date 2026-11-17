"""OFF-03B.2 pure tests: asymmetric signatures, fail-closed gating, scope fencing.

No PostgreSQL or production secrets. CI also runs isolated PostgreSQL17 tests.
"""
import base64
import json
import unittest
from contextlib import contextmanager
from datetime import datetime
from unittest.mock import patch
from uuid import uuid4

from pydantic import SecretStr

from app.auth.permissions import permissions_for_profiles
from app.auth.service import AuthenticatedUser
from app.config import settings
from app.offline_scope import service
from app.offline_scope.signing import (
    DOMAIN, OfflineSigningUnavailable, SCHEMA, canonical_payload,
    decode_b64, encode_b64, load_signer, sign_scope, verify_scope
)

DEMO_SEED = encode_b64(bytes(range(1, 33)))
DEVICE = uuid4()


def operator(profile="OPERACION", *, must_change=False):
    return AuthenticatedUser(uuid4(), "synthetic", "Synthetic User", (profile,),
                             permissions_for_profiles((profile,)), must_change, frozenset({"BOBINAS"}))


class SigningTest(unittest.TestCase):
    def signer(self):
        with patch.object(settings, "offline_scope_issue_enabled", True), patch.object(
                settings, "offline_scope_signing_seed_b64url", SecretStr(DEMO_SEED)):
            return load_signer()

    def example_payload(self):
        return {"schema": SCHEMA, "audience": "vinto-offline-readiness", "issuer": "vinto-backend",
                "device_key": str(DEVICE), "subject_user_id": str(uuid4()),
                "issued_at": "2026-11-17T12:00:00Z", "snapshot_id": str(uuid4()),
                "kind": "scope_readiness_only", "captures_enabled": False, "form_scopes": []}

    def test_disabled_by_default_and_missing_invalid_keys_never_sign(self):
        with patch.object(settings, "offline_scope_issue_enabled", False), patch.object(
                settings, "offline_scope_signing_seed_b64url", SecretStr(DEMO_SEED)):
            with self.assertRaises(OfflineSigningUnavailable):
                load_signer()
        with patch.object(settings, "offline_scope_issue_enabled", True), patch.object(
                settings, "offline_scope_signing_seed_b64url", None):
            with self.assertRaises(OfflineSigningUnavailable):
                load_signer()
        with patch.object(settings, "offline_scope_issue_enabled", True), patch.object(
                settings, "offline_scope_signing_seed_b64url", SecretStr("bad-key")):
            with self.assertRaises(OfflineSigningUnavailable):
                load_signer()

    def test_ed25519_signature_is_verifiable_only_with_pinned_public_key(self):
        signer = self.signer()
        payload = self.example_payload()
        signed = sign_scope(payload, signer=signer)
        self.assertEqual(signed["algorithm"], "Ed25519")
        self.assertTrue(verify_scope(signed, trusted_public_key_b64url=signer.public_b64url))
        wrong = encode_b64(bytes(range(32)))
        self.assertFalse(verify_scope(signed, trusted_public_key_b64url=wrong))
        self.assertNotIn(DEMO_SEED, json.dumps(signed))
        self.assertEqual(len(decode_b64(signed["signature_b64url"])), 64)

    def test_tampering_context_device_issued_time_permissions_and_signature_fail(self):
        signer = self.signer()
        signed = sign_scope(self.example_payload(), signer=signer)
        for attr, value in (
                ("device_key", str(uuid4())),
                ("issued_at", "2026-11-18T12:00:00Z"),
                ("subject_user_id", str(uuid4())),
                ("captures_enabled", True),
                ("form_scopes", [{"machine_code":"MP1", "form_code":"VINTO-P1-01"}])):
            tampered = {**signed, "payload": {**signed["payload"], attr: value}}
            with self.subTest(attribute=attr):
                self.assertFalse(verify_scope(tampered, trusted_public_key_b64url=signer.public_b64url))
        tampered = {**signed, "signature_b64url": encode_b64(bytes(64))}
        self.assertFalse(verify_scope(tampered, trusted_public_key_b64url=signer.public_b64url))

    def test_canonical_json_order_and_domain_separation(self):
        signer = self.signer()
        body = self.example_payload()
        self.assertEqual(canonical_payload(body), canonical_payload(dict(reversed(list(body.items())))))
        signed = sign_scope(body, signer=signer)
        self.assertTrue(verify_scope(signed, trusted_public_key_b64url=signer.public_b64url))
        self.assertTrue(DOMAIN.endswith(b"\0"))
        with self.assertRaises(ValueError):
            decode_b64("a=")


class _Cursor:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows


class FakeConnection:
    def __init__(self, rows):
        self.rows = rows
        self.in_transaction = False
        self.executed = []

    @contextmanager
    def transaction(self):
        self.in_transaction = True
        try:
            yield self
        finally:
            self.in_transaction = False

    def execute(self, query, args):
        self.executed.append((query, args))
        return _Cursor(self.rows)


class IssueTests(unittest.TestCase):
    def signer(self):
        with patch.object(settings, "offline_scope_issue_enabled", True), patch.object(
                settings, "offline_scope_signing_seed_b64url", SecretStr(DEMO_SEED)):
            return load_signer()

    def test_accepts_only_real_engine_decisions_in_locked_transaction(self):
        user=operator()
        conn=FakeConnection([("MP1","VINTO-P1-01"),("MP1","VINTO-P1-06")])
        grants=[uuid4(),uuid4()]
        decisions=[]

        def authorizer(connection, principal, operation, machine, form, *, lock):
            self.assertTrue(connection.in_transaction, "signature must be made under DB transaction")
            self.assertTrue(lock, "no non-locking authorization for offline snapshot")
            self.assertEqual(principal.user_id, user.user_id)
            decisions.append((operation.value,machine,form))
            from app.authz.engine import Decision
            return Decision(True,"allowed","ALLOWED", operation.value, principal.user_id,
                            machine,form,effective_version=3,grant_id=grants[len(decisions)-1])

        with patch.object(service,"authorize",side_effect=authorizer):
            signed=service.issue_scope(conn,user,device_key=DEVICE,machine_codes=["MP1"],signer=self.signer())
        self.assertEqual([x["form_code"] for x in signed["payload"]["form_scopes"]],
                         ["VINTO-P1-01","VINTO-P1-06"])
        self.assertEqual([x["form_version"] for x in signed["payload"]["form_scopes"]],[3,3])
        self.assertFalse(signed["payload"]["captures_enabled"])
        self.assertNotIn("expires_at",signed["payload"])
        self.assertEqual(signed["payload"]["device_key"],str(DEVICE))
        self.assertIn("revoked_at IS NULL",conn.executed[0][0])
        self.assertTrue(verify_scope(signed,trusted_public_key_b64url=self.signer().public_b64url))

    def test_no_grants_no_capture_permission_and_passwd_change_fail_closed(self):
        signer=self.signer()
        with self.assertRaises(service.OfflineScopeDenied):
            service.issue_scope(FakeConnection([]),operator(),device_key=DEVICE,machine_codes=["MP1"],signer=signer)
        with self.assertRaises(service.OfflineScopeDenied):
            service.issue_scope(FakeConnection([("MP1","VINTO-P1-06")]),operator("DATA_BALTREK"),
                                device_key=DEVICE,machine_codes=["MP1"],signer=signer)
        with self.assertRaises(service.OfflineScopeDenied):
            service.issue_scope(FakeConnection([("MP1","VINTO-P1-06")]),operator(must_change=True),
                                device_key=DEVICE,machine_codes=["MP1"],signer=signer)

    def test_invalid_devices_repeated_machine_codes_and_excess_pairs_deny(self):
        signer=self.signer()
        user=operator()
        for codes in ([],["MP1","MP1"],["MP1"]*26):
            with self.subTest(codes=codes):
                with self.assertRaises(service.OfflineScopeDenied):
                    service.issue_scope(FakeConnection([]),user,device_key=DEVICE,machine_codes=codes,signer=signer)
        with self.assertRaises(service.OfflineScopeDenied):
            service.issue_scope(FakeConnection([]),user,device_key=uuid4(),machine_codes=["MP1","MP1"],signer=signer)
        with self.assertRaises(service.OfflineScopeTooLarge):
            service.issue_scope(FakeConnection([("MP1","VINTO-P1-06")]*201),
                                user,device_key=DEVICE,machine_codes=["MP1"],signer=signer)


if __name__ == "__main__":
    unittest.main()
