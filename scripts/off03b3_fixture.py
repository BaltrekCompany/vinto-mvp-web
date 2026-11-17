#!/usr/bin/env python3
"""OFF-03B.3 synthetic Ed25519 fixture generator using the REAL backend signer.

Never uses a production secret or records. The device ID is supplied by the
browser only in the mock test and signed here to test cross-language validity.
"""
import hashlib
import json
import os
from pathlib import Path
import sys
from uuid import UUID

BACKEND = Path(__file__).resolve().parents[1] / "backend"
sys.path.insert(0, str(BACKEND))
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
from app.offline_scope.signing import AUDIENCE, ISSUER, SCHEMA, SigningKey, encode_b64, sign_scope

USER_ID = "11111111-1111-4111-8111-111111111111"
DEVICE_ID = "22222222-2222-4222-8222-222222222222"
SNAPSHOT_ID = "33333333-3333-4333-8333-333333333333"
GRANT_ID = "44444444-4444-4444-8444-444444444444"

def signer(rotated=False):
    private = Ed25519PrivateKey.from_private_bytes(bytes(range(33,65)) if rotated else bytes(range(1,33)))
    public = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return SigningKey(private, encode_b64(public), "ed25519-" + hashlib.sha256(public).hexdigest()[:20])

def sign_for_device(device_key, user_id=USER_ID, rotated=False):
    assert UUID(device_key).version == 4
    payload = {
        "schema": SCHEMA, "issuer": ISSUER, "audience": AUDIENCE,
        "snapshot_id": SNAPSHOT_ID, "subject_user_id": user_id,
        "device_key": device_key,
        "issued_at": "2026-11-17T12:00:00Z",
        "kind": "scope_readiness_only", "captures_enabled": False,
        "form_scopes": [
            {"machine_code": "MP1", "form_code": "VINTO-P1-18",
             "form_version": 3, "grant_id": GRANT_ID,
             "operation": "quality_machine_capture"}
        ]
    }
    return sign_scope(payload, signer=signer(rotated))


# OFF-03C.2: synthetic full quality-machine definition package signed by the
# same REAL Python Ed25519 signing module; never uses production data/keys.
def synthetic_quality_package(signed_scope):
    from app.offline_scope.signing import (
        PACKAGE_SCHEMA, PACKAGE_AUDIENCE, ISSUER, canonical_payload, sign_quality_package
    )
    scope=signed_scope["payload"]
    item=scope["form_scopes"][0]
    assert item["form_code"]=="VINTO-P1-18"
    def field(key,label,value_type,order,required,options=None):
        return {"key":key,"label":label,"description":"","value_type":value_type,
            "source":"manual","required":required,"unit":None,"classification":None,
            "proposal":None,"needs_validation":False,"display_order":order,
            "calculation_rule":None,"options":options or []}
    definition={
        "form_code":item["form_code"],"form_name":"Porcentaje de consistencia",
        "form_version":item["form_version"],"area":"quality",
        "source_definition_checksum":"a"*64,
        "published_at":"2026-11-17T10:00:00+00:00",
        "groups":[],"fields":[
            field("numero_de_cuba","Número de cuba","text",1,True),
            field("masa_humeda_g","Masa húmeda g","decimal",2,True),
            field("observaciones","Observaciones","textarea",3,False)
        ],
        "calculated_rules":{},"option_dependencies":[],
        "recipe_bundle_included":False,"capture_eligible":False,
        "note":"Synthetic QA-only definition; no industrial captures."
    }
    payload={
        "schema":PACKAGE_SCHEMA,"issuer":ISSUER,"audience":PACKAGE_AUDIENCE,
        "kind":"quality_definition_readiness_only","captures_enabled":False,
        "package_id":"55555555-5555-4555-8555-555555555555",
        "scope_snapshot_id":scope["snapshot_id"],
        "subject_user_id":scope["subject_user_id"],
        "device_key":scope["device_key"],
        "machine_code":item["machine_code"],
        "form_code":item["form_code"],"form_version":item["form_version"],
        "grant_id":item["grant_id"],"issued_at":"2026-11-17T12:01:00Z",
        "content_sha256":hashlib.sha256(canonical_payload(definition)).hexdigest(),
        "definition":definition,
    }
    return sign_quality_package(payload,signer=signer())

if __name__ == "__main__":
    path = os.environ.get("OFF03B3_FIXTURE_JSON")
    if not path:
        raise SystemExit("OFF03B3_FIXTURE_JSON required")
    signed_scope=sign_for_device(DEVICE_ID)
    fixture = {"envelope":signed_scope,"quality_package":synthetic_quality_package(signed_scope),
               "identity":{"ownerId": USER_ID, "deviceKey": DEVICE_ID}}
    Path(path).write_text(json.dumps(fixture,ensure_ascii=False,sort_keys=True),encoding="utf-8")
    print("OFF03B3_PYTHON_SIGNED_FIXTURE=PASS",flush=True)
