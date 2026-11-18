#!/usr/bin/env python3
"""OFF-03C.4 synthetic renewal scenarios, signed with the REAL backend signer.

Every identity, grant, form and key is synthetic (deterministic seeds). Nothing
here comes from a production database and no production secret is used.
Scenario scopes differ in time, grants and versions so the browser/Node tests can
exercise renewal, rollback, reduction, key rotation, and cross-identity cases.
"""
import hashlib
import json
import os
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from off03b3_fixture import DEVICE_ID, USER_ID, signer  # noqa: E402  (also puts backend on sys.path)
from app.offline_scope.signing import (  # noqa: E402
    AUDIENCE, ISSUER, PACKAGE_AUDIENCE, PACKAGE_SCHEMA, SCHEMA, canonical_payload,
    sign_quality_package, sign_scope,
)

OTHER_USER_ID = "77777777-7777-4777-8777-777777777777"
OTHER_DEVICE_ID = "88888888-8888-4888-8888-888888888888"
FORMS = {
    "VINTO-P1-18": "Porcentaje de consistencia",
    "VINTO-P1-22": "Control de pasta",
    "VINTO-P1-26": "Control de humedad",
    "VINTO-P1-27": "Control de gramaje",
}


def uid(*parts):
    return str(uuid.UUID(bytes=hashlib.sha256("|".join(parts).encode()).digest()[:16], version=4))


def pair(machine, form, version, grant=None):
    return {"machine_code": machine, "form_code": form, "form_version": version,
            "grant_id": grant or uid("grant", machine, form), "operation": "quality_machine_capture"}


def scope(tag, issued_at, pairs, *, user=USER_ID, device=DEVICE_ID, rotated=False):
    payload = {
        "schema": SCHEMA, "issuer": ISSUER, "audience": AUDIENCE,
        "snapshot_id": uid("snapshot", tag), "subject_user_id": user, "device_key": device,
        "issued_at": issued_at, "kind": "scope_readiness_only", "captures_enabled": False,
        "form_scopes": pairs,
    }
    return sign_scope(payload, signer=signer(rotated))


def package(scope_envelope, machine, form, *, version=None, label="v", scope_snapshot=None, rotated=False):
    sp = scope_envelope["payload"]
    item = next(x for x in sp["form_scopes"] if x["machine_code"] == machine and x["form_code"] == form)
    version = item["form_version"] if version is None else version

    def field(key, text, vtype, order, required):
        return {"key": key, "label": text, "description": "", "value_type": vtype, "source": "manual",
                "required": required, "unit": None, "classification": None, "proposal": None,
                "needs_validation": False, "display_order": order, "calculation_rule": None, "options": []}
    definition = {
        "form_code": form, "form_name": FORMS[form], "form_version": version, "area": "quality",
        "source_definition_checksum": hashlib.sha256(f"{form}:{version}".encode()).hexdigest(),
        "published_at": "2026-11-17T10:00:00+00:00", "groups": [],
        # Content depends ONLY on the form version (as in production): two snapshots that grant the same
        # version carry the byte-identical definition, which the progression rule requires.
        "fields": [field("numero_de_cuba", f"Número de cuba v{version}", "text", 1, True),
                   field("masa_g", f"Masa g v{version}", "decimal", 2, True)],
        "calculated_rules": {}, "option_dependencies": [], "recipe_bundle_included": False,
        "capture_eligible": False, "note": "Synthetic QA-only definition; no industrial captures.",
    }
    payload = {
        "schema": PACKAGE_SCHEMA, "issuer": ISSUER, "audience": PACKAGE_AUDIENCE,
        "kind": "quality_definition_readiness_only", "captures_enabled": False,
        "package_id": uid("package", sp["snapshot_id"], machine, form, str(version), label),
        "scope_snapshot_id": scope_snapshot or sp["snapshot_id"],
        "subject_user_id": sp["subject_user_id"], "device_key": sp["device_key"],
        "machine_code": machine, "form_code": form, "form_version": version,
        "grant_id": item["grant_id"], "issued_at": sp["issued_at"],
        "content_sha256": hashlib.sha256(canonical_payload(definition)).hexdigest(),
        "definition": definition,
    }
    return sign_quality_package(payload, signer=signer(rotated))


def build():
    base = [pair("MP1", "VINTO-P1-18", 3), pair("MP1", "VINTO-P1-22", 2)]
    scopes = {
        "old": scope("old", "2026-11-17T12:00:00Z", base),
        "new": scope("new", "2026-11-17T12:30:00Z", base),
        "newer": scope("newer", "2026-11-17T12:45:00Z", [pair("MP1", "VINTO-P1-18", 4), pair("MP1", "VINTO-P1-22", 2)]),
        "reduced": scope("reduced", "2026-11-17T13:00:00Z", [pair("MP1", "VINTO-P1-22", 2)]),
        "downgrade": scope("downgrade", "2026-11-17T13:10:00Z", [pair("MP1", "VINTO-P1-18", 2), pair("MP1", "VINTO-P1-22", 2)]),
        "older": scope("older", "2026-11-17T11:00:00Z", base),
        "same_second": scope("same_second", "2026-11-17T12:00:00Z", base),
        "rotated_key": scope("rotated", "2026-11-17T14:00:00Z", base, rotated=True),
        "other_user": scope("other_user", "2026-11-17T14:10:00Z", base, user=OTHER_USER_ID),
        "other_device": scope("other_device", "2026-11-17T14:20:00Z", base, device=OTHER_DEVICE_ID),
    }
    packages = {}
    for name, env in scopes.items():
        rotated = name == "rotated_key"
        for item in env["payload"]["form_scopes"]:
            packages[f"{name}|{item['machine_code']}|{item['form_code']}"] = package(
                env, item["machine_code"], item["form_code"], label=name, rotated=rotated)
    bad = {
        # properly signed, but the version differs from the granted one
        "incompatible_version": package(scopes["new"], "MP1", "VINTO-P1-18", version=9, label="incompat"),
        # properly signed package that still belongs to the previous snapshot
        "wrong_snapshot": package(scopes["new"], "MP1", "VINTO-P1-18", label="wrongsnap",
                                  scope_snapshot=scopes["old"]["payload"]["snapshot_id"]),
    }
    return {"identity": {"ownerId": USER_ID, "deviceKey": DEVICE_ID},
            "other_identity": {"ownerId": OTHER_USER_ID, "deviceKey": DEVICE_ID},
            "scopes": scopes, "packages": packages, "bad": bad}


if __name__ == "__main__":
    path = os.environ.get("OFF03C4_FIXTURE_JSON")
    if not path:
        raise SystemExit("OFF03C4_FIXTURE_JSON required")
    Path(path).write_text(json.dumps(build(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print("OFF03C4_PYTHON_SIGNED_RENEWAL_FIXTURE=PASS", flush=True)
