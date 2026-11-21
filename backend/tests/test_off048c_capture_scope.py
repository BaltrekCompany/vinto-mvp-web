"""OFF-04.8C: independently signed capture scope cannot inherit readiness authority.

Pure synthetic Ed25519 fixtures, with no network or database. This verifier is not
an issuer, and no operational route is enabled by these tests.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.offline_capture.contract import CaptureIn, canonical_sha256
from app.offline_scope.signing import encode_b64, canonical_payload, sign_scope
from app.quality.offline_capture_scope import (AUDIENCE, DOMAIN, KIND, SCHEMA,
                                                verified_capture_scope)

OWNER = UUID("11111111-1111-4111-8111-111111111111")
DEVICE = UUID("33333333-3333-4333-8333-333333333333")
SNAPSHOT = UUID("55555555-5555-4555-8555-555555555555")


def scenario():
    key = Ed25519PrivateKey.generate()
    pub = encode_b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    import hashlib
    key_id = "ed25519-" + hashlib.sha256(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()[:20]
    at = datetime(2026, 11, 20, 18, 0, tzinfo=timezone.utc)
    payload = {
        "schema": SCHEMA, "issuer": "vinto-backend", "audience": AUDIENCE, "kind": KIND,
        "snapshot_id": str(SNAPSHOT), "subject_user_id": str(OWNER), "device_key": str(DEVICE),
        "issued_at": at.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "expires_at": (at + timedelta(hours=2)).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "form_scopes": [{
            "machine_code": "MP1", "form_code": "VINTO-P1-22", "form_version": 2,
            "operation": "quality_machine_capture", "grant_id": str(uuid4()),
        }],
    }
    def signed(source=payload):
        return {
            "algorithm": "Ed25519", "key_id": key_id, "public_key_b64url": pub,
            "payload": source, "signature_b64url": encode_b64(key.sign(DOMAIN + canonical_payload(source))),
        }
    body = {"synthetic": False, "payload": {"numero_de_cuba": "QA"}}
    cap = CaptureIn(capture_id=uuid4(), author_user_id=OWNER, device_key=DEVICE,
                    form_code="VINTO-P1-22", form_version=2, machine_code="MP1",
                    scope_snapshot_id=SNAPSHOT, context_version=str(SNAPSHOT),
                    payload_sha256=canonical_sha256(body), payload=body)
    who = SimpleNamespace(user_id=OWNER)
    def verify(envelope, *, snapshot_active=lambda snapshot, user: True, capture=cap, current=at + timedelta(minutes=1)):
        return verified_capture_scope(envelope, who, capture, trusted_public_key_b64url=pub,
                                      now=current, snapshot_active=snapshot_active)
    return signed, payload, cap, verify, at


def test_exact_signed_live_capture_scope_is_accepted():
    signed, payload, cap, verify, at = scenario()
    assert verify(signed())


def test_readiness_scope_never_becomes_capture_authority():
    signed, payload, cap, verify, at = scenario()
    readiness = {**payload, "audience": "vinto-offline-readiness", "kind": "scope_readiness_only"}
    assert not verify(signed(readiness))
    assert not verify({**signed(), "payload": {**payload, "kind": "scope_readiness_only"}})


@pytest.mark.parametrize("patch", [
    {"snapshot_id": str(uuid4())},
    {"subject_user_id": str(uuid4())},
    {"device_key": str(uuid4())},
    {"form_scopes": []},
    {"form_scopes": [{"machine_code": "MP3", "form_code": "VINTO-P1-22", "form_version": 2,
                      "operation": "quality_machine_capture", "grant_id": str(uuid4())}]},
    {"form_scopes": [{"machine_code": "MP1", "form_code": "VINTO-P1-22", "form_version": 1,
                      "operation": "quality_machine_capture", "grant_id": str(uuid4())}]},
    {"form_scopes": [{"machine_code": "MP1", "form_code": "VINTO-P1-22", "form_version": 2,
                      "operation": "quality_bobbin_capture", "grant_id": str(uuid4())}]},
    {"extra": "untrusted"},
])
def test_signed_but_mismatched_claims_are_denied(patch):
    signed, payload, cap, verify, at = scenario()
    assert not verify(signed({**payload, **patch}))


def test_expired_revoked_and_missing_snapshot_checker_are_denied():
    signed, payload, cap, verify, at = scenario()
    assert not verify(signed(), current=at + timedelta(hours=3))
    assert not verify(signed(), snapshot_active=lambda snap, user: False)
    assert not verified_capture_scope(signed(), SimpleNamespace(user_id=OWNER), cap,
                                      trusted_public_key_b64url=signed()["public_key_b64url"],
                                      now=at + timedelta(minutes=1), snapshot_active=None)


def test_tampered_signature_and_wrong_key_are_denied():
    signed, payload, cap, verify, at = scenario()
    corrupted = {**signed(), "signature_b64url": encode_b64(bytes(64))}
    assert not verify(corrupted)
    new_key = Ed25519PrivateKey.generate()
    wrong = encode_b64(new_key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    assert not verified_capture_scope(signed(), SimpleNamespace(user_id=OWNER), cap,
                                      trusted_public_key_b64url=wrong,
                                      now=at + timedelta(minutes=1), snapshot_active=lambda snap, user: True)


def test_full_signature_domain_prevents_readiness_replay():
    signed, payload, cap, verify, at = scenario()
    key = Ed25519PrivateKey.generate()
    from app.offline_scope.signing import SigningKey
    pub = encode_b64(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw))
    import hashlib
    key_id = "ed25519-" + hashlib.sha256(key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).hexdigest()[:20]
    readonly_payload = {**payload, "schema": "vinto.offline.scope.v1", "audience": "vinto-offline-readiness"}
    legacy = sign_scope(readonly_payload, signer=SigningKey(key, pub, key_id))
    assert not verified_capture_scope(legacy, SimpleNamespace(user_id=OWNER), cap,
                                      trusted_public_key_b64url=pub,
                                      now=at + timedelta(minutes=1), snapshot_active=lambda snap, user: True)
