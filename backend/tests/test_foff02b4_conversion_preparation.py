"""FOFF-02B.4 — signer cannot authorize CAPTURE and binds operational identity."""
import uuid
from datetime import datetime, timezone
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from app.foff_conversion_preparation import DOMAIN, sign_conversion_preparation
from app.quality.offline_capture_scope import _canonical
import base64
import pytest

def _decode(x):
    return base64.urlsafe_b64decode(x + "=" * (-len(x) % 4))

def _context():
    return {
        "assignment_id": str(uuid.uuid4()),
        "work_order_id": str(uuid.uuid4()),
        "line_id": str(uuid.uuid4()),
        "machine_code": "GAMBINI",
        "form_code": "VINTO-P1-11",
        "form_version": 4,
        "article_code": "10342",
        "shift_code": "MANANA",
        "operating_date": "2026-11-27",
        "reference_sha256": "b" * 64,
        "context_digest": "a" * 64,
    }

def test_preparation_signed_and_separate_from_capture_scope():
    envelope = sign_conversion_preparation(
        seed_hex="01" * 32, user_id=str(uuid.uuid4()),
        device_key=str(uuid.uuid4()), context=_context(),
        now=datetime(2026,11,27,12,tzinfo=timezone.utc))
    p=envelope["payload"]
    assert p["kind"] == "preparation_only"
    assert p["schema"] != "vinto.offline.capture_scope.v1"
    assert p["audience"] != "vinto-offline-operational-capture"
    assert p["context"]["form_version"] == 4
    assert p["issued_at"] == "2026-11-27T12:00:00Z"
    assert p["expires_at"] == "2026-11-28T00:00:00Z"
    public=Ed25519PublicKey.from_public_bytes(_decode(envelope["public_key_b64url"]))
    public.verify(_decode(envelope["signature_b64url"]),DOMAIN+_canonical(p))
    altered=dict(p)
    altered["context"]={**p["context"],"machine_code":"OMET_I"}
    with pytest.raises(Exception):
        public.verify(_decode(envelope["signature_b64url"]),DOMAIN+_canonical(altered))

@pytest.mark.parametrize("change", [
    {"form_code":"VINTO-P1-18"},{"form_version":0},{"machine_code":"bad space"},
    {"assignment_id":"x"},{"context_digest":"bad"}
])
def test_bad_context_refused(change):
    with pytest.raises((ValueError,TypeError)):
        sign_conversion_preparation(seed_hex="01"*32,user_id=str(uuid.uuid4()),
            device_key=str(uuid.uuid4()),context={**_context(),**change})
