#!/usr/bin/env python3
"""OFF-04.8 v6 synthetic CAPTURE-authority scenarios, signed with the REAL backend signer/domain (app.quality.offline_capture_authority._signed). Deterministic ids; times relative to NOW
(fixed in the JSON so the Node test is not clock dependent). Nothing here is a production secret or database."""
import copy, hashlib, json, os, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from off03b3_fixture import DEVICE_ID, USER_ID, signer  # noqa: E402  (also puts backend on sys.path)
from off03c4_fixture import OTHER_DEVICE_ID, OTHER_USER_ID, uid  # noqa: E402
from app.offline_scope.signing import canonical_payload, encode_b64, sign_scope  # noqa: E402
from app.quality.offline_capture_authority import _signed  # noqa: E402
from app.quality.offline_capture_scope import AUDIENCE, DOMAIN, KIND, SCHEMA  # noqa: E402

NOW = datetime(2026, 11, 24, 15, 0, 0, tzinfo=timezone.utc)
VERSIONS = {"VINTO-P1-18": 2, "VINTO-P1-19": 1, "VINTO-P1-20": 1, "VINTO-P1-21": 2, "VINTO-P1-22": 2, "VINTO-P1-24": 5, "VINTO-P1-25": 4, "VINTO-P1-26": 3, "VINTO-P1-27": 2, "VINTO-P1-28": 1}
BOBBIN = {"VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28"}
t = lambda d: d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def entry(machine, form, version, grant=None, operation=None):
    return {"machine_code": machine, "form_code": form, "form_version": version, "operation": operation or ("quality_bobbin_capture" if form in BOBBIN else "quality_machine_capture"),
            "grant_id": grant or uid("grant", machine, form)}


def pairs(machine="MP1", **over):
    return [entry(machine, f, over.get("versions", {}).get(f, v), grant=over.get("grants", {}).get(f)) for f, v in VERSIONS.items() if f not in over.get("drop", ())]


def authority(tag, issued_ago_h, remaining_h, plist, *, user=USER_ID, device=DEVICE_ID, rotated=False, tamper=None, readiness_domain=False):
    issued = NOW - timedelta(hours=issued_ago_h)
    expires = NOW + timedelta(hours=remaining_h)
    assert expires - issued <= timedelta(hours=24), tag
    payload = {"schema": SCHEMA, "issuer": "vinto-backend", "audience": AUDIENCE, "kind": KIND, "snapshot_id": uid("capsnap", tag), "subject_user_id": user, "device_key": device,
               "issued_at": t(issued), "expires_at": t(expires), "form_scopes": copy.deepcopy(plist)}
    env = _signed(payload, signer(rotated))
    if readiness_domain:   # signed correctly but in the READINESS domain: must never verify as CAPTURE
        env["signature_b64url"] = encode_b64(signer(rotated).private.sign(b"VINTO-OFFLINE-SCOPE-V1\x00" + canonical_payload(payload)))
    if tamper:
        tamper(env)
    return env


def build():
    base = pairs()
    out = {"identity": {"ownerId": USER_ID, "deviceKey": DEVICE_ID}, "other_user": {"ownerId": OTHER_USER_ID, "deviceKey": DEVICE_ID}, "other_device": {"ownerId": USER_ID, "deviceKey": OTHER_DEVICE_ID},
           "now_iso": t(NOW), "pin": signer(False).public_b64url, "rotated_pin": signer(True).public_b64url, "fresh": base, "versions": VERSIONS, "env": {}}
    e = out["env"]
    e["ok"] = authority("ok", 1, 23, base)
    e["ok_older"] = authority("ok-older", 3, 21, base)                                   # same coverage, older issued_at
    e["rem_8h_exact"] = authority("rem8", 16, 8, base)                                   # exactly 8h left: NOT reusable
    e["rem_8h_plus"] = authority("rem8p", 15.99, 8.01, base)                             # 8h + 36s left: reusable
    e["rem_7h"] = authority("rem7", 17, 7, base)
    e["expired"] = authority("exp", 24, -0.01, base)
    e["future"] = authority("future", -1, 24, base)                                      # issued in the future (device behind / forged)
    e["no_p122"] = authority("nop22", 1, 23, pairs(drop=("VINTO-P1-22",)))             # pair removed (revoked) in the CANDIDATE
    e["extra_machine"] = authority("extra", 1, 23, base + pairs("MP3"))                  # candidate wider than the fresh scope (escalation)
    e["version_bump"] = authority("vbump", 1, 23, pairs(versions={"VINTO-P1-22": 3}))
    e["grant_changed"] = authority("grant", 1, 23, pairs(grants={"VINTO-P1-22": uid("othergrant")}))
    e["wrong_operation"] = authority("wrongop", 1, 23, [dict(x, operation="quality_machine_capture" if x["form_code"] in BOBBIN else "quality_bobbin_capture") for x in base])
    e["other_user"] = authority("ouser", 1, 23, base, user=OTHER_USER_ID)
    e["other_device"] = authority("odev", 1, 23, base, device=OTHER_DEVICE_ID)
    e["rotated_key"] = authority("rot", 1, 23, base, rotated=True)

    def t_exp(env): env["payload"]["expires_at"] = t(NOW + timedelta(hours=23, minutes=30))
    def t_pair(env): env["payload"]["form_scopes"][0]["form_version"] += 1
    e["tampered_expiry"] = authority("tamp1", 1, 22, base, tamper=t_exp)
    e["tampered_pair"] = authority("tamp2", 1, 23, base, tamper=t_pair)
    e["readiness_domain"] = authority("rdom", 1, 23, base, readiness_domain=True)
    e["duplicate_entry"] = authority("dup", 1, 23, base + [base[0]])
    # a READINESS scope presented where a CAPTURE authority is expected
    rp = {"schema": "vinto.offline.scope.v1", "issuer": "vinto-backend", "audience": "vinto-offline-readiness", "snapshot_id": uid("rs"), "subject_user_id": USER_ID, "device_key": DEVICE_ID,
          "issued_at": t(NOW - timedelta(hours=1)), "kind": "scope_readiness_only", "captures_enabled": False, "form_scopes": base}
    e["readiness_as_capture"] = sign_scope(rp, signer=signer(False))
    return out


if __name__ == "__main__":
    path = os.environ.get("OFF048V_FIXTURE_JSON")
    if not path:
        raise SystemExit("OFF048V_FIXTURE_JSON required")
    Path(path).write_text(json.dumps(build(), ensure_ascii=False, sort_keys=True), encoding="utf-8")
    print("OFF048V_PYTHON_SIGNED_FIXTURE=PASS", flush=True)
