#!/usr/bin/env python3
"""OFF-04.8T synthetic scenarios for the known OFF-04.7 pilot-synthetic -> real package transition, signed with the REAL backend signer.

The OLD packages are built with the pilot's own generator (app.qa_pilot_auth.synthetic_definition), exactly what the OFF-04.7 QA pilot issued. The NEW packages
are 'real-like': same published-form source checksum, different body (the real note). Nothing here uses a production database or secret."""
import copy, hashlib, json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from off03b3_fixture import DEVICE_ID, USER_ID, signer  # noqa: E402  (also puts backend on sys.path)
from off03c4_fixture import OTHER_DEVICE_ID, OTHER_USER_ID, pair, scope, uid  # noqa: E402
from app.offline_scope.signing import ISSUER, PACKAGE_AUDIENCE, PACKAGE_SCHEMA, canonical_payload, sign_quality_package  # noqa: E402
from app.qa_pilot_auth import synthetic_definition  # noqa: E402

VERSIONS = {"VINTO-P1-18": 2, "VINTO-P1-19": 1, "VINTO-P1-20": 1, "VINTO-P1-21": 2, "VINTO-P1-22": 2, "VINTO-P1-24": 5, "VINTO-P1-25": 4, "VINTO-P1-26": 3, "VINTO-P1-27": 2, "VINTO-P1-28": 1}
FOUR = ["VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27"]
REAL_NOTE = "Readiness preview only. No OT, shifts, recipes, capture or acceptance."


def sign_package(scope_env, machine, form, definition, *, label, rotated=False, subject=None, device=None):
    sp = scope_env["payload"]
    item = next(x for x in sp["form_scopes"] if x["machine_code"] == machine and x["form_code"] == form)
    payload = {
        "schema": PACKAGE_SCHEMA, "issuer": ISSUER, "audience": PACKAGE_AUDIENCE, "kind": "quality_definition_readiness_only", "captures_enabled": False,
        "package_id": uid("package", sp["snapshot_id"], machine, form, label), "scope_snapshot_id": sp["snapshot_id"],
        "subject_user_id": subject or sp["subject_user_id"], "device_key": device or sp["device_key"], "machine_code": machine, "form_code": form,
        "form_version": definition["form_version"], "grant_id": item["grant_id"], "issued_at": sp["issued_at"],
        "content_sha256": hashlib.sha256(canonical_payload(definition)).hexdigest(), "definition": definition,
    }
    return sign_quality_package(payload, signer=signer(rotated))


def real_definition(form, version):
    d = copy.deepcopy(synthetic_definition(form, version)); d["note"] = REAL_NOTE; d["published_at"] = "2026-11-17T10:00:00+00:00"
    return d


def build():
    pairs = [pair("MP1", f, v) for f, v in VERSIONS.items()]
    pilot_scope = scope("pilot", "2026-11-21T10:00:00Z", pairs)
    real_scope = scope("real", "2026-11-24T02:00:00Z", [pair("MP1", f, v, grant=uid("realgrant", f)) for f, v in VERSIONS.items()])
    real2_scope = scope("real2", "2026-11-24T02:20:00Z", [pair("MP1", f, v, grant=uid("realgrant2", f)) for f, v in VERSIONS.items()])
    lower_scope = scope("lower", "2026-11-24T02:10:00Z", [pair("MP1", "VINTO-P1-22", 1, grant=uid("lowergrant"))])
    rotated_scope = scope("rotated", "2026-11-24T02:30:00Z", pairs, rotated=True)
    scopes = {"pilot": pilot_scope, "real": real_scope, "real2": real2_scope, "lower": lower_scope, "rotated": rotated_scope}
    pk = {}
    for f, v in VERSIONS.items():
        pk[f"pilot|{f}"] = sign_package(pilot_scope, "MP1", f, synthetic_definition(f, v), label="pilot")
        pk[f"real|{f}"] = sign_package(real_scope, "MP1", f, real_definition(f, v), label="real")
    f = "VINTO-P1-22"
    # real -> synthetic (reverse direction): the OLD is the real package of scope 'real', the NEW is the pilot body under a later scope
    pk["reverse_new_synthetic"] = sign_package(real2_scope, "MP1", f, synthetic_definition(f, 2), label="reverse")
    # OLD forged from the pilot body (valid signature!) but with the field text altered: same synthetic note, NOT a pinned hash
    forged = synthetic_definition(f, 2); forged["fields"][0]["label"] = forged["fields"][0]["label"] + " (alterado)"
    pk["forged_old"] = sign_package(pilot_scope, "MP1", f, forged, label="forged")
    # OLD whose ONLY difference from the pilot is the note
    note_only = synthetic_definition(f, 2); note_only["note"] = "Synthetic QA-only definition; no industrial captures. "
    pk["note_only_old"] = sign_package(pilot_scope, "MP1", f, note_only, label="noteonly")
    # NEW with a different real body at the same version (non-pilot -> non-pilot): must stay rejected
    other = real_definition(f, 2); other["fields"][0]["label"] = other["fields"][0]["label"] + " v2b"
    pk["real_other_body"] = sign_package(real2_scope, "MP1", f, other, label="otherbody")
    # NEW lower version (grant version 1)
    low = real_definition(f, 2); low["form_version"] = 1
    pk["lower_new"] = sign_package(lower_scope, "MP1", f, low, label="lower")
    # NEW with a different published-form source checksum
    src = real_definition(f, 2); src["source_definition_checksum"] = hashlib.sha256(b"another published form").hexdigest()
    pk["other_source_new"] = sign_package(real2_scope, "MP1", f, src, label="othersrc")
    # wrong key / foreign subject / foreign device (signed correctly, but not for this phone)
    pk["rotated_key"] = sign_package(rotated_scope, "MP1", f, real_definition(f, 2), label="rotated", rotated=True)
    pk["foreign_subject"] = sign_package(real_scope, "MP1", f, real_definition(f, 2), label="foreignsubj", subject=OTHER_USER_ID)
    pk["foreign_device"] = sign_package(real_scope, "MP1", f, real_definition(f, 2), label="foreigndev", device=OTHER_DEVICE_ID)
    known = {form: [v, hashlib.sha256(canonical_payload(synthetic_definition(form, v))).hexdigest(), synthetic_definition(form, v)["source_definition_checksum"]] for form, v in VERSIONS.items()}
    return {"identity": {"ownerId": USER_ID, "deviceKey": DEVICE_ID}, "other_identity": {"ownerId": OTHER_USER_ID, "deviceKey": DEVICE_ID}, "other_device_identity": {"ownerId": USER_ID, "deviceKey": OTHER_DEVICE_ID},
            "scopes": scopes, "packages": pk, "known_pilot": known, "four": FOUR, "pilot_note": synthetic_definition("VINTO-P1-22", 2)["note"]}


if __name__ == "__main__":
    path = os.environ.get("OFF048T_FIXTURE_JSON")
    if not path:
        raise SystemExit("OFF048T_FIXTURE_JSON required")
    Path(path).write_text(json.dumps(build(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print("OFF048T_PYTHON_SIGNED_FIXTURE=PASS", flush=True)
