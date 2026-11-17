"""OFF-03B.2 signed scope envelopes; strictly read-only, never a capture token.

Sign with Ed25519 and domain-separated canonical JSON. The seed lives in an
environment SecretStr; public key accompanies the envelope for offline *testing*
only and MUST be anchored to an authenticated HTTPS enrolment before it is trusted.
"""
import base64
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from app.config import settings

DOMAIN = b"VINTO-OFFLINE-SCOPE-V1\x00"
SCHEMA = "vinto.offline.scope.v1"
ISSUER = "vinto-backend"
AUDIENCE = "vinto-offline-readiness"
_B64URL = re.compile(r"^[A-Za-z0-9_-]+$")


class OfflineSigningUnavailable(Exception):
    """No valid server-side key is configured. Fail closed without exposing details."""


def encode_b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def decode_b64(text: str, expected_len: int | None = None) -> bytes:
    if not isinstance(text, str) or not _B64URL.fullmatch(text):
        raise ValueError("invalid b64url")
    try:
        result = base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, base64.binascii.Error) as error:
        raise ValueError("invalid b64url") from error
    if (expected_len is not None and len(result) != expected_len) or encode_b64(result) != text:
        raise ValueError("non-canonical b64url")
    return result


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


@dataclass(frozen=True)
class SigningKey:
    private: Ed25519PrivateKey
    public_b64url: str
    key_id: str


def load_signer() -> SigningKey:
    value = settings.offline_scope_signing_seed_b64url
    if not settings.offline_scope_issue_enabled or value is None:
        raise OfflineSigningUnavailable()
    try:
        seed = decode_b64(value.get_secret_value(), 32)
        private = Ed25519PrivateKey.from_private_bytes(seed)
    except (ValueError, TypeError) as error:
        raise OfflineSigningUnavailable() from None
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    # Derived key ID prevents accidental publication under a stale human-configured ID.
    return SigningKey(private, encode_b64(public), "ed25519-" + hashlib.sha256(public).hexdigest()[:20])


def sign_scope(payload: dict[str, Any], *, signer: SigningKey | None = None) -> dict[str, Any]:
    signer = signer if signer is not None else load_signer()
    assert payload["schema"] == SCHEMA and payload["audience"] == AUDIENCE
    signature = signer.private.sign(DOMAIN + canonical_payload(payload))
    return {
        "algorithm": "Ed25519",
        "key_id": signer.key_id,
        "public_key_b64url": signer.public_b64url,
        "payload": payload,
        "signature_b64url": encode_b64(signature),
    }


def verify_scope(envelope: dict[str, Any], *, trusted_public_key_b64url: str) -> bool:
    """Offline signature/integrity primitive. Public key MUST be pinned independently.

    Signature verification does NOT imply user is currently active, machine/OT
    assignments are still valid, or a delayed capture may be accepted by API.
    """
    try:
        if not isinstance(envelope, dict) or set(envelope) != {
            "algorithm", "key_id", "public_key_b64url", "payload", "signature_b64url"
        } or envelope["algorithm"] != "Ed25519":
            return False
        payload = envelope["payload"]
        if not isinstance(payload, dict) or payload.get("schema") != SCHEMA or payload.get("audience") != AUDIENCE or payload.get("issuer") != ISSUER:
            return False
        pub = decode_b64(trusted_public_key_b64url, 32)
        if envelope["public_key_b64url"] != trusted_public_key_b64url:
            return False
        if envelope["key_id"] != "ed25519-" + hashlib.sha256(pub).hexdigest()[:20]:
            return False
        signature = decode_b64(envelope["signature_b64url"], 64)
        Ed25519PublicKey.from_public_bytes(pub).verify(signature, DOMAIN + canonical_payload(payload))
        return True
    except (KeyError, TypeError, ValueError, InvalidSignature):
        return False
