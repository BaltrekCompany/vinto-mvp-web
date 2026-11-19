#!/usr/bin/env python3
"""OFF-04.2-R2 consistency and recovery of the consolidated laboratory database (synthetic data only).

No backend, no network beyond loopback, no production data. Each scenario uses its own persistent
browser profile; "restart" closes and relaunches that profile. Every page is instrumented so that any
fetch/XHR/beacon/WebSocket attempt is recorded and asserted to be zero.
"""
import http.server
import json
import os
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

FX = json.loads(Path(os.environ["OFF04_FIXTURE_JSON"]).read_text(encoding="utf-8"))
HARNESS = Path(os.environ["OFF04_HARNESS_JS"]).read_bytes()
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
SECRET = "VINTO OFF04 synthetic draft secret 2208!!"
ID, OTHER = FX["identity"], FX["other_identity"]
MARKERS = ["C-001-SINT", "120.50", "reforzada", "Observación sintética única"]
GOOD = {"numero_de_cuba": "C-001-SINT", "tipo_pasta": "reforzada", "masa_humeda_g": "120,50", "masa_seca_g": "30.1",
        "cantidad_muestras": "3", "fecha_muestreo": "2026-11-18", "hora_muestreo": "08:30", "muestra_valida": True,
        "observaciones": "Observación sintética única"}
D1, D2 = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
D3, D4, D5 = "dddddddd-dddd-4ddd-8ddd-dddddddddddd", "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee", "ffffffff-ffff-4fff-8fff-ffffffffffff"
requests_seen = []


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body, kind = (HARNESS, "text/javascript") if self.path == "/harness.js" else (
            b'<!doctype html><meta charset="utf-8"><title>off04</title><script src="/harness.js"></script>', "text/html")
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


class Tab:
    def __init__(self, page):
        self.page = page

    def call(self, fn, *args):
        return self.page.evaluate("([f,a]) => window.H[f](...a)", [fn, list(args)])


class Browser:
    def __init__(self, pw, profile):
        self.pw, self.profile, self.ctx = pw, profile, None

    def open(self, unlock=True):
        kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
        self.ctx = self.pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
            service_workers="block", **kwargs)
        self.ctx.on("request", lambda r: requests_seen.append(r.url))
        self.tab = self.new_tab(unlock)
        return self

    def new_tab(self, unlock=True):
        page = self.ctx.new_page()
        page.set_default_timeout(120000)
        page.goto(URL)
        page.wait_for_function("() => !!window.H")
        tab = Tab(page)
        if unlock:
            assert tab.call("unlock", SECRET) is True
        return tab

    def call(self, fn, *args):
        return self.tab.call(fn, *args)

    def kill(self):
        self.ctx.close()
        self.ctx = None


def baseline(pw, tmp, name):
    b = Browser(pw, Path(tmp) / name)
    b.open(unlock=False)
    b.call("enrol", ID, SECRET)
    assert b.call("unlock", SECRET) is True
    b.call("seed", FX["scope"], FX["package"])
    return b


def no_plaintext(b):
    raw = b.call("rawDrafts")
    for marker in MARKERS + ["numero_de_cuba", "masa_humeda_g", "Laboratorio de Calidad"]:
        assert marker not in raw, "plaintext leaked into IndexedDB: " + marker
    return raw




def pending_rows(b):
    return b.call("rawPendingRows")


def invariant(b, ids):
    """Every pending must freeze exactly the draft revision it was created from; the draft must be frozen."""
    for d in ids:
        p = b.call("pendingLoad", d)
        if p.get("found"):
            dr = b.call("load", d)
            assert dr["ok"] and dr["revision"] == p["payload"]["source_revision"], ("divergent revisions", d, dr.get("revision"), p["payload"]["source_revision"])
            assert b.call("save", d, GOOD, dr["revision"])["reason"] == "pending_local"


FAILED = []


def case(name):
    def deco(fn):
        try:
            fn()
        except Exception as error:   # any deviation (assertion, missing key, harness error) is a failure of the case
            FAILED.append(name)
            print(json.dumps({"case": name, "result": "FAIL", "detail": (type(error).__name__ + ": " + str(error))[:300]}), flush=True)
        return fn
    return deco


with tempfile.TemporaryDirectory(prefix="vinto-off042r2-") as tmp, sync_playwright() as pw:
    # ---- H1/R1: a save commits while the transition is sealing: never a pending older than its draft ----
    @case("R1_save_during_transition_never_leaves_a_stale_pending")
    def _c1():
        b = baseline(pw, tmp, "r1")
        assert b.call("save", D1, GOOD, None)["ok"]
        r = b.call("queueVsSave", D1, 1, {**GOOD, "observaciones": "REV2 DEL OPERARIO"})
        assert r["ok"] is False and r["reason"] == "conflict", r
        assert pending_rows(b) == []
        d = b.call("load", D1)
        assert d["revision"] == 2 and d["values"]["observaciones"] == "REV2 DEL OPERARIO"
        assert b.call("save", D1, {**GOOD, "observaciones": "sigue editable"}, 2)["revision"] == 3        # no permanent block
        q = b.call("queue", D1, 3)
        assert q["ok"] and q["created"] is True and q["sourceRevision"] == 3
        assert b.call("pendingLoad", D1)["payload"]["draft"]["values"]["observaciones"] == "sigue editable"
        invariant(b, [D1])
        report("R1_save_during_transition_never_leaves_a_stale_pending")
        b.kill()

    # ---- H1/R2: a pending commits while a save is sealing: the save is refused, never a newer draft ----
    @case("R2_pending_during_save_refuses_the_save_without_divergence")
    def _c2():
        b = baseline(pw, tmp, "r2")
        assert b.call("save", D1, GOOD, None)["ok"]
        r = b.call("saveVsQueue", D1, 1, {**GOOD, "observaciones": "REV2 TRAS EL PENDIENTE"})
        assert r["ok"] is False and r["reason"] == "pending_local", r
        d = b.call("load", D1)
        assert d["revision"] == 1
        p = b.call("pendingLoad", D1)
        assert p["found"] and p["payload"]["source_revision"] == 1
        assert b.call("queue", D1, 1)["created"] is False
        invariant(b, [D1])
        report("R2_pending_during_save_refuses_the_save_without_divergence")
        b.kill()

    # ---- H2/S1: a malformed pending is quarantined (visible), blocks its draft explicitly, never unblocks silently ----
    @case("S1_malformed_pending_is_quarantined_visible_and_never_unblocks_the_draft")
    def _c3():
        b = baseline(pw, tmp, "s1")
        for d in (D1, D2, D3):
            assert b.call("save", d, GOOD, None)["ok"] and b.call("queue", d, 1)["created"] is True
        caps = {x["draftId"]: x["capture_id"] for x in pending_rows(b)}
        before = b.call("rawPending")
        b.call("tamperPending", caps[D1], "status")          # malformed row
        b.call("tamperPending", caps[D2], "draft_id")        # association to the draft is broken
        for d in (D1, D2):
            r = b.call("save", d, {**GOOD, "observaciones": "no"}, 1)
            assert r["ok"] is False and r["reason"] in ("quarantined", "pending_local"), (d, r)
            assert r["reason"] == "quarantined", (d, r)
            r = b.call("queue", d, 1)
            assert r["ok"] is False and r["reason"] in ("quarantined", "conflict", "invalid"), (d, r)
        lst = b.call("pendingList")
        assert lst["ok"] and len(lst["quarantine"]) >= 2, lst
        assert {q["id"] for q in lst["quarantine"]} >= {caps[D1], D1, D2}, lst
        assert b.call("pendingLoad", D3)["found"] and b.call("save", D3, GOOD, 1)["reason"] == "pending_local"
        assert b.call("save", D4, GOOD, None)["ok"]                                  # unrelated drafts keep working
        rows = pending_rows(b)
        assert len(rows) == 3, "malformed evidence must be kept"
        report("S1_malformed_pending_is_quarantined_visible_and_never_unblocks_the_draft")
        b.kill()

    # ---- H3/S2: losing ONLY the laboratory database must not reactivate anything ----
    @case("S2_lab_database_loss_is_fail_closed_nothing_is_reactivated")
    def _c4():
        b = baseline(pw, tmp, "s2")
        assert b.call("save", D1, {**GOOD, "observaciones": "original"}, None)["ok"]
        assert b.call("queue", D1, 1)["created"] is True
        b.call("dropLabDb")
        for label, r in (("save", b.call("save", D1, {**GOOD, "observaciones": "cambiado"}, 1)), ("queue", b.call("queue", D1, 1)),
                         ("new draft", b.call("save", D2, GOOD, None)), ("list", b.call("list")), ("pending list", b.call("pendingList"))):
            assert r["ok"] is False and r["reason"] == "lab_lost", (label, r)
        assert b.call("labExists") is False, "a lost laboratory database must NOT be recreated"
        assert b.call("realOutbox") == 0
        report("S2_lab_database_loss_is_fail_closed_nothing_is_reactivated")
        b.kill()

    def legacy_world(name):
        """Legacy data exactly as OFF-04.1/04.2 left it: drafts in the application store, pendings in the former queue database."""
        b = baseline(pw, tmp, name)
        assert b.call("legacySave", D1, GOOD, None)["ok"]                                    # A: complete, never queued
        assert b.call("legacySave", D2, {"numero_de_cuba": "incompleto"}, None)["ok"]        # B: incomplete
        assert b.call("legacySave", D3, GOOD, None)["ok"]                                    # C: will be damaged
        assert b.call("legacySave", D4, GOOD, None)["ok"] and b.call("legacyQueue", D4)["ok"]   # D: legacy pending
        assert b.call("legacySave", D5, GOOD, None)["ok"] and b.call("legacyQueue", D5)["ok"]   # E: legacy pending ...
        assert b.call("legacySave", D5, {**GOOD, "observaciones": "VERSION POSTERIOR"}, 1)["ok"]  # ... and a LATER draft revision (old race)
        b.call("legacyTamper", D3)
        return b

    # ---- M1: prepare -> verify -> commit -> verify-committed; legacy data is never written ----
    @case("M1_migration_is_non_destructive_verified_and_idempotent")
    def _m1():
        b = legacy_world("m1")
        legacy_before = b.call("legacyRaw")
        plan = b.call("migratePlan")
        assert plan["ok"] and plan["drafts"] == 4 and plan["pendings"] == 2 and plan["quarantine"] == 1 and plan["divergent"] == 1, plan
        assert b.call("rawDraftRows") == [] and b.call("legacyRaw") == legacy_before, "prepare/verify must write nothing"
        rep = b.call("migrate")
        assert rep["ok"] and rep["migratedDrafts"] == 4 and rep["migratedPendings"] == 2 and rep["quarantined"] == 1 and rep["divergent"] == 1, rep
        assert b.call("legacyRaw") == legacy_before, "legacy data must be byte-identical after the migration"
        rows = {r["id"]: r for r in b.call("rawDraftRows")}
        legacy_drafts = {r["id"]: r for r in json.loads(legacy_before)[0]}
        assert set(rows) == {D1, D2, D4, D5}
        for d, r in rows.items():
            assert r["sealed"] == legacy_drafts[d]["sealed"], "sealed blobs are copied verbatim"
        assert "frozenBy" not in rows[D1] and "frozenBy" not in rows[D2] and rows[D4]["frozenBy"] and rows[D5]["frozenBy"]
        q = b.call("rawQuarantine")
        assert len(q) == 1 and q[0]["source"] == "legacy_draft" and q[0]["reason"] == "undecryptable", q
        meta = {m["key"]: m["value"] for m in b.call("labMeta")}
        assert any(k.startswith("migration:") for k in meta) and "instance" in meta
        # migrated drafts behave: A and B stay editable, D/E are frozen, E shows the FROZEN content, never the later draft
        assert b.call("save", D1, {**GOOD, "observaciones": "editable"}, 1)["revision"] == 2         # an unqueued legacy draft stays editable
        assert b.call("save", D4, GOOD, 1)["reason"] == "pending_local"
        fz = b.call("frozen", D5)["payload"]
        assert fz["source_revision"] == 1 and fz["draft"]["values"]["observaciones"] != "VERSION POSTERIOR", fz
        assert b.call("load", D5)["revision"] == 2 and b.call("save", D5, GOOD, 2)["reason"] == "pending_local"
        assert b.call("queue", D1, 2)["created"] is True
        assert b.call("realOutbox") == 0
        # idempotent: a second run changes nothing, and a legacy draft appearing later is NOT silently imported
        snap = b.call("rawDrafts")
        again = b.call("migrate")
        assert again["ok"] and again["alreadyMigrated"] is True
        assert b.call("legacySave", "cccccccc-cccc-4ccc-8ccc-cccccccccccc", GOOD, None)["ok"]
        assert b.call("migrate")["alreadyMigrated"] is True and b.call("rawDrafts") == snap
        b.kill()
        report("M1_migration_is_non_destructive_verified_and_idempotent")

    # ---- M2: any failure during the migration leaves the laboratory untouched and the procedure re-runnable ----
    @case("M2_failure_quota_and_wrong_key_during_migration_change_nothing")
    def _m2():
        b = legacy_world("m2")
        legacy_before = b.call("legacyRaw")
        for label, arm, reason in (("write error mid-way", lambda: b.call("failAddOn", 3), "storage"),
                                   ("quota", lambda: b.call("failAddOn", 1, "QuotaExceededError"), "quota"),
                                   ("failure after an add inside the transaction", lambda: b.call("failAddOn", 2, "DataError", True), "storage")):
            arm()
            r = b.call("migrate")
            b.call("clearFaults")
            assert r["ok"] is False and r["reason"] == reason, (label, r)
            assert b.call("rawDraftRows") == [] and b.call("rawPendingRows") == [] and b.call("rawQuarantine") == [], label
            assert not any(m["key"].startswith("migration:") for m in b.call("labMeta")), label
            assert b.call("legacyRaw") == legacy_before, label
        b.call("useForeignKey")
        r = b.call("migrate")
        assert r["ok"] is False and r["reason"] == "locked", r                        # a wrong key is never a verdict of damage
        assert b.call("rawDraftRows") == [] and b.call("rawQuarantine") == [] and b.call("legacyRaw") == legacy_before
        assert b.call("unlock", SECRET) is True
        rep = b.call("migrate")
        assert rep["ok"] and rep["migratedDrafts"] == 4 and rep["migratedPendings"] == 2, rep      # re-runnable after every failure
        assert b.call("legacyRaw") == legacy_before
        b.kill()
        b = baseline(pw, tmp, "m2-single")                                                  # a lone damaged draft, nothing else
        assert b.call("legacySave", D1, GOOD, None)["ok"]
        b.call("legacyTamper", D1)
        r = b.call("migrate")
        assert r["ok"] is False and r["reason"] == "locked", r                              # unproven key: indistinguishable from a wrong key
        assert b.call("rawDraftRows") == []
        rep = b.call("migrate", True)                                                       # key proven (as the lab UI does): quarantine
        assert rep["ok"] and rep["migratedDrafts"] == 0 and rep["quarantined"] == 1, rep
        assert len(b.call("rawQuarantine")) == 1
        b.kill()
        report("M2_failure_quota_and_wrong_key_during_migration_change_nothing")

    # ---- M3: losing the laboratory database after migrating never re-imports or reactivates legacy drafts ----
    @case("M3_lab_loss_after_migration_does_not_reactivate_legacy_drafts")
    def _m3():
        b = legacy_world("m3")
        legacy_before = b.call("legacyRaw")
        assert b.call("migrate")["ok"]
        b.call("dropOnlyV2")
        for label, r in (("migrate", b.call("migrate")), ("save legacy draft", b.call("save", D1, GOOD, 1)), ("list", b.call("list")),
                         ("queue legacy draft", b.call("queue", D1, 1)), ("new draft", b.call("save", D1.replace("a", "b"), GOOD, None))):
            assert r["ok"] is False and r["reason"] == "lab_lost", (label, r)
        assert b.call("legacyRaw") == legacy_before and b.call("rawDraftRows") == [] and b.call("labExists") is False   # the lab was NOT recreated
        b.call("clearLabEpoch")                                                           # explicit decision needed: still not automatic
        assert b.call("labEpoch") is None
        b.kill()
        # a replaced database (epoch does not match) is refused too
        b = baseline(pw, tmp, "m3b")
        assert b.call("save", D1, GOOD, None)["ok"]
        b.tab.page.evaluate("() => localStorage.setItem('vinto-off04lab-epoch', '11111111-1111-4111-8111-111111111111')")
        r = b.call("save", D2, GOOD, None)
        assert r["ok"] is False and r["reason"] == "lab_lost", r
        b.tab.page.evaluate("() => localStorage.removeItem('vinto-off04lab-epoch')")
        assert b.call("save", D2, GOOD, None)["ok"] is True                                # only the epoch lost: database is intact
        assert b.call("labEpoch") is not None
        b.kill()
        report("M3_lab_loss_after_migration_does_not_reactivate_legacy_drafts")

    # ---- M4: two tabs migrate concurrently; other browser/identity has nothing to migrate ----
    @case("M4_two_tabs_migrate_once_and_other_browser_sees_nothing")
    def _m4():
        b = legacy_world("m4")
        legacy_before = b.call("legacyRaw")
        tab2 = b.new_tab()
        start = "() => { window.__m = H.migrate(); }"
        b.tab.page.evaluate(start); tab2.page.evaluate(start)
        ra = b.tab.page.evaluate("async () => await window.__m"); rb = tab2.page.evaluate("async () => await window.__m")
        assert ra["ok"] and rb["ok"], (ra, rb)
        assert len(b.call("rawDraftRows")) == 4 and len(b.call("rawPendingRows")) == 2 and len(b.call("rawQuarantine")) == 1
        assert b.call("legacyRaw") == legacy_before
        b.kill()
        other = baseline(pw, tmp, "m4-other")
        plan = other.call("migratePlan")
        assert plan["ok"] and plan["drafts"] == 0 and plan["pendings"] == 0 and plan["quarantine"] == 0, plan
        other.kill()
        report("M4_two_tabs_migrate_once_and_other_browser_sees_nothing")

assert not FAILED, "FAILED: " + ", ".join(FAILED)
print("OFF04_2_R2_CONSISTENCY_CHROME=PASS", flush=True)
