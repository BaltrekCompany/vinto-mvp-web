#!/usr/bin/env python3
"""OFF-03C.4 real-Chrome IndexedDB integration: atomic scope+package renewal.

Synthetic identities/forms/signatures only (real backend signer via off03c4_fixture.py).
No backend, no network beyond loopback, no production data. Each scenario runs in its
own persistent browser profile; "restart" means closing and relaunching that profile.
"""
import functools
import http.server
import json
import os
import shutil
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

FIXTURE = json.loads(Path(os.environ["OFF03C4_FIXTURE_JSON"]).read_text(encoding="utf-8"))
HARNESS = Path(os.environ["OFF03C4_HARNESS_JS"]).read_bytes()
CHANNEL = os.environ.get("OFF03C4_CHROME_CHANNEL", "chrome")
SECRET = "VINTO OFF03C4 synthetic renewal secret 7141!!"
ID = FIXTURE["identity"]
OTHER = FIXTURE["other_identity"]
SC, PK, BAD = FIXTURE["scopes"], FIXTURE["packages"], FIXTURE["bad"]
Q18, Q22 = "MP1|VINTO-P1-18", "MP1|VINTO-P1-22"
OLD_SNAP, NEW_SNAP = SC["old"]["payload"]["snapshot_id"], SC["new"]["payload"]["snapshot_id"]


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/harness.js":
            body, kind = HARNESS, "text/javascript"
        else:
            body, kind = b'<!doctype html><meta charset="utf-8"><title>off03c4</title><script src="/harness.js"></script>', "text/html"
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://localhost:{server.server_address[1]}/"


def full_plan(scope_name, **overrides):
    """Default online answers: the named scope plus every package it grants."""
    env = SC[scope_name]
    packages = {}
    for item in env["payload"]["form_scopes"]:
        key = f'{item["machine_code"]}|{item["form_code"]}'
        packages[key] = {"envelope": PK[f"{scope_name}|{key}"]}
    plan = {"scope": {"envelope": env}, "packages": packages}
    for k, v in overrides.items():
        if k == "scope":
            plan["scope"] = v
        else:
            plan["packages"][k] = v
    return plan


class Session:
    def __init__(self, pw, profile):
        self.pw, self.profile, self.ctx, self.page = pw, profile, None, None

    def open(self, unlock=True):
        self.ctx = self.pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile), headless=True,
            **({"channel": CHANNEL} if CHANNEL != "bundled" else {}),
            args=["--no-sandbox", "--disable-dev-shm-usage"], service_workers="block")
        self.page = self.ctx.new_page()
        self.page.set_default_timeout(120000)
        self.page.goto(URL)
        self.page.wait_for_function("() => !!window.H")
        if unlock:
            assert self.call("unlock", SECRET) is True
        return self

    def call(self, fn, *args):
        return self.page.evaluate("([f,a]) => window.H[f](...a)", [fn, list(args)])

    def start_unawaited(self, fn, *args):
        self.page.evaluate("([f,a]) => { window.__pending = window.H[f](...a); return true; }", [fn, list(args)])

    def kill(self):
        self.ctx.close()

    def close(self):
        if self.ctx:
            self.ctx.close()
            self.ctx = None


def baseline(pw, tmp, name):
    """Fresh profile enrolled with the OLD scope and its two packages (initial flow)."""
    session = Session(pw, Path(tmp) / name)
    session.open(unlock=False)
    session.call("enrol", ID, SECRET)
    assert session.call("unlock", SECRET) is True
    session.call("seed", SC["old"], [PK["old|" + Q18], PK["old|" + Q22]])
    return session


def view(session):
    return session.call("view")


def assert_old_intact(session, before_raw, status="legacy_unverified"):
    assert session.call("rawSnapshot") == before_raw, "stored bytes changed"
    v = view(session)
    assert v["scope"]["snapshotId"] == SC["old"]["payload"]["snapshot_id"], v
    assert sorted(p["pair"] for p in v["packages"]) == [Q18, Q22] and all(p["snapshot"] == OLD_SNAP for p in v["packages"]), v
    assert v["status"] == status, v
    return v


with tempfile.TemporaryDirectory(prefix="vinto-off03c4-") as tmp, sync_playwright() as pw:
    # ---- 01 valid and complete renewal (+ 05 reopen after confirmed renewal) ----
    s = baseline(pw, tmp, "valid")
    v = view(s)
    assert v["status"] == "legacy_unverified" and len(v["packages"]) == 2
    r = s.call("renew", full_plan("new"))
    assert r["ok"] is True and r["snapshotId"] == SC["new"]["payload"]["snapshot_id"], r
    assert len(r["renewedPackages"]) == 2 and r["reduced"] is False, r
    v = view(s)
    assert v["scope"]["snapshotId"] == SC["new"]["payload"]["snapshot_id"] and v["status"] == "renewed_online", v
    assert all(p["snapshot"] == NEW_SNAP for p in v["packages"]) and len(v["packages"]) == 2, v
    assert s.call("rawCounts") == {"scopes": 1, "packages": 2} and s.call("superseded") == 0
    report("01_valid_complete_renewal_replaces_scope_and_packages_together")
    s.kill()
    s.open()
    v = view(s)
    assert v["scope"]["snapshotId"] == SC["new"]["payload"]["snapshot_id"] and v["status"] == "renewed_online", v
    assert len(v["packages"]) == 2 and all(p["snapshot"] == NEW_SNAP for p in v["packages"]), v
    report("05_reopen_after_confirmed_renewal_reads_new_set")
    # a second, newer renewal over the already renewed set (+ real version progression)
    r = s.call("renew", full_plan("newer"))
    assert r["ok"] is True, r
    v = view(s)
    assert dict((p["pair"], p["version"]) for p in v["packages"]) == {Q18: 4, Q22: 2}, v
    report("01b_progressive_renewal_accepts_higher_form_version")
    s.close()

    # ---- 02 network error before the package is obtained ----
    s = baseline(pw, tmp, "network")
    raw = s.call("rawSnapshot")
    for plan in (full_plan("new", **{Q22: {"network": True}}), full_plan("new", scope={"network": True}),
                 full_plan("new", **{Q18: {"status": 503}})):
        r = s.call("renew", plan)
        assert r["ok"] is False and r["stage"] == "prepare" and r["reason"] in ("network", "server_unavailable"), r
        assert_old_intact(s, raw)
    assert r["reason"] == "server_unavailable"
    report("02_network_error_keeps_previous_set_and_is_never_success")
    s.close()

    # ---- 03 interruption while preparing, then the browser is killed ----
    s = baseline(pw, tmp, "interrupt")
    raw = s.call("rawSnapshot")
    s.start_unawaited("renew", full_plan("new", **{Q22: {"hang": True}}))
    s.page.wait_for_timeout(2500)           # scope fetched, first package fetched, second hangs
    s.kill()
    s.open()
    assert_old_intact(s, raw)
    r = s.call("renew", full_plan("new"))   # nothing stuck: a later clean renewal works
    assert r["ok"] is True
    report("03_interrupted_preparation_then_browser_killed_keeps_previous_set")
    s.close()

    # ---- 04 failure before commit (encryption) and inside the transaction ----
    s = baseline(pw, tmp, "precommit")
    raw = s.call("rawSnapshot")
    s.call("failEncryptOn", 2)
    r = s.call("renew", full_plan("new"))
    s.call("clearFaults")
    assert r["ok"] is False and r["stage"] == "prepare" and r["reason"] == "storage", r
    assert_old_intact(s, raw)
    report("04a_failure_before_indexeddb_commit_changes_nothing")
    s.call("failPutOn", 2)                  # second put (a package) fails INSIDE the transaction
    r = s.call("renew", full_plan("new"))
    s.call("clearFaults")
    assert r["ok"] is False and r["stage"] == "commit" and r["reason"] == "commit_failed", r
    assert_old_intact(s, raw)
    report("04b_failure_inside_transaction_rolls_back_scope_and_packages")
    # 04c: a commit split over two transactions would leave a NEW scope with OLD packages.
    s.call("failSecondWriteTransaction")
    r = s.call("renew", full_plan("new"))
    s.call("clearFaults")
    v = view(s)
    assert len(v["packages"]) == 2 and all("unreadable" not in p and p["snapshot"] == v["scope"]["snapshotId"]
                                          for p in v["packages"]), ("mixed or partial set", r, v)
    assert (r["ok"] is True) == (v["scope"]["snapshotId"] == NEW_SNAP), (r, v)
    report("04c_scope_and_packages_always_change_together_never_mixed")
    s.close()

    # ---- 06 altered signature / hash / key ----
    s = baseline(pw, tmp, "tamper")
    raw = s.call("rawSnapshot")

    def flip(text):
        return ("B" if text[0] == "A" else "A") + text[1:]
    bad_scope = json.loads(json.dumps(SC["new"]))
    bad_scope["signature_b64url"] = flip(bad_scope["signature_b64url"])
    pkg_sig = json.loads(json.dumps(PK["new|" + Q18]))
    pkg_sig["signature_b64url"] = flip(pkg_sig["signature_b64url"])
    pkg_body = json.loads(json.dumps(PK["new|" + Q18]))
    pkg_body["payload"]["definition"]["fields"][0]["label"] = "Etiqueta manipulada"
    pkg_hash = json.loads(json.dumps(PK["new|" + Q18]))
    pkg_hash["payload"]["content_sha256"] = "f" * 64
    cases = [("scope signature", full_plan("new", scope={"envelope": bad_scope}), "invalid"),
             ("package signature", full_plan("new", **{Q18: {"envelope": pkg_sig}}), "invalid"),
             ("package body", full_plan("new", **{Q18: {"envelope": pkg_body}}), "invalid"),
             ("package hash", full_plan("new", **{Q18: {"envelope": pkg_hash}}), "invalid"),
             ("rotated key", full_plan("rotated_key"), "pin_mismatch")]
    for label, plan, reason in cases:
        r = s.call("renew", plan)
        assert r["ok"] is False and r["reason"] == reason, (label, r)
        assert_old_intact(s, raw)
    report("06_altered_signature_hash_or_key_rejected_without_changes")
    s.close()

    # ---- 07 user / browser change ----
    s = baseline(pw, tmp, "identity")
    raw = s.call("rawSnapshot")
    for label, plan, opts in (("scope of another user", full_plan("other_user"), {}),
                              ("scope of another browser", full_plan("other_device"), {}),
                              ("another identity in session", full_plan("new"), {"asIdentity": OTHER})):
        r = s.call("renew", plan, opts)
        assert r["ok"] is False and r["reason"] == "identity_mismatch", (label, r)
        assert_old_intact(s, raw)
    report("07_other_user_or_browser_cannot_overwrite_the_set")
    s.close()

    # ---- 08 reduced and revoked scope ----
    s = baseline(pw, tmp, "reduced")
    raw_old = s.call("rawSnapshot")
    r = s.call("renew", full_plan("reduced"))
    assert r["ok"] is True and r["reduced"] is True and r["removedPairs"] == [{"machine_code": "MP1", "form_code": "VINTO-P1-18"}], r
    v = view(s)
    assert [p["pair"] for p in v["packages"]] == [Q22] and v["scope"]["pairs"] == ["MP1|VINTO-P1-22|v2"], v
    assert s.call("rawCounts")["packages"] == 2 and s.call("superseded") == 1     # old P1-18 kept, inert
    assert s.call("discard", "yes")["ok"] is False and s.call("rawCounts")["packages"] == 2
    assert s.call("discard", "DISCARD_SUPERSEDED_PACKAGES") == {"ok": True, "n": 1}
    assert s.call("rawCounts")["packages"] == 1 and view(s)["packages"][0]["pair"] == Q22
    report("08a_reduced_scope_retires_forms_and_cleanup_needs_explicit_confirmation")
    s.close()

    s = baseline(pw, tmp, "revoked")
    raw = s.call("rawSnapshot")
    before = json.loads(raw)
    r = s.call("renew", full_plan("new", scope={"status": 401}))
    assert r["ok"] is False and r["reason"] == "auth" and s.call("rawSnapshot") == raw
    r = s.call("renew", full_plan("new", scope={"status": 403}))
    assert r["ok"] is False and r["reason"] == "revoked", r
    after = json.loads(s.call("rawSnapshot"))
    assert after["packages"] == before["packages"], "revocation must not touch encrypted packages"
    assert after["scopes"][0]["sealed"] == before["scopes"][0]["sealed"] and "renewal" in after["scopes"][0]
    v = view(s)
    assert v["status"] == "revocation_known" and v["scope"]["snapshotId"] == SC["old"]["payload"]["snapshot_id"], v
    assert len(v["packages"]) == 2                  # nothing deleted; the UI withholds it
    s.kill()
    s.open()
    assert view(s)["status"] == "revocation_known"
    r = s.call("renew", full_plan("new"))           # only a verified online renewal clears the flag
    assert r["ok"] is True and view(s)["status"] == "renewed_online"
    report("08b_revocation_recorded_sealed_data_preserved_and_cleared_only_by_renewal")
    s.close()

    # ---- 09 package incompatible with the granted version / snapshot, downgrade ----
    s = baseline(pw, tmp, "incompat")
    raw = s.call("rawSnapshot")
    for label, plan, reason in (
            ("version differs from grant", full_plan("new", **{Q18: {"envelope": BAD["incompatible_version"]}}), "incompatible"),
            ("package of previous snapshot", full_plan("new", **{Q18: {"envelope": BAD["wrong_snapshot"]}}), "incompatible"),
            ("lower version than stored", full_plan("downgrade"), "rollback")):
        r = s.call("renew", plan)
        assert r["ok"] is False and r["reason"] == reason, (label, r)
        assert_old_intact(s, raw)
    report("09_incompatible_or_downgraded_package_never_mixes_with_new_scope")
    s.close()

    # ---- 10 snapshot older than the accepted one ----
    s = baseline(pw, tmp, "rollback")
    raw = s.call("rawSnapshot")
    for label, plan in (("older", full_plan("older")), ("same second, other snapshot", full_plan("same_second"))):
        r = s.call("renew", plan)
        assert r["ok"] is False and r["reason"] == "rollback", (label, r)
        assert_old_intact(s, raw)
    assert s.call("renew", full_plan("new"))["ok"] is True
    r = s.call("renew", full_plan("old"))           # replaying the very first snapshot after a newer one
    assert r["ok"] is False and r["reason"] == "rollback", r
    assert view(s)["scope"]["snapshotId"] == SC["new"]["payload"]["snapshot_id"]
    report("10_older_or_replayed_snapshot_rejected")
    s.close()

    # ---- 11 local unlock failure and unreadable data ----
    s = baseline(pw, tmp, "unlock")
    raw = s.call("rawSnapshot")
    assert s.call("unlock", "wrong passphrase value 12345!!") is False
    s.call("useForeignKey")
    r = s.call("renew", full_plan("new"))
    assert r["ok"] is False and r["reason"] == "needs_recovery", r
    assert s.call("rawSnapshot") == raw
    assert s.call("unlock", SECRET) is True
    s.call("corruptFirstPackage")
    raw_corrupt = s.call("rawSnapshot")
    r = s.call("renew", full_plan("new"))
    assert r["ok"] is False and r["reason"] == "needs_recovery" and s.call("rawSnapshot") == raw_corrupt, r
    r = s.call("renew", full_plan("new"), {"allowReplaceUnreadable": True})
    assert r["ok"] is True, r
    v = view(s)
    assert len(v["packages"]) == 2 and all(p["snapshot"] == NEW_SNAP for p in v["packages"]), v
    report("11_unlock_failure_and_corrupt_data_need_explicit_recovery")
    s.close()

    # ---- 12 browser killed while the commit transaction is open ----
    s = baseline(pw, tmp, "killcommit")
    raw = s.call("rawSnapshot")
    s.call("spinAfterFirstPut", 6000)
    s.start_unawaited("renew", full_plan("new"))
    s.page.wait_for_timeout(2500)           # prepared, first put issued, main thread holds the transaction
    s.kill()
    s.open()
    assert_old_intact(s, raw)
    assert s.call("renew", full_plan("new"))["ok"] is True and view(s)["status"] == "renewed_online"
    report("12_browser_killed_during_open_transaction_leaves_previous_set_intact")
    s.close()

    shutil.rmtree(tmp, ignore_errors=True)
print("OFF03C4_RENEWAL_INDEXEDDB_CHROME=PASS", flush=True)
