#!/usr/bin/env python3
"""OFF-04.2 real-Chrome IndexedDB integration for the SIMULATED local pending queue (synthetic data only).

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


def no_plaintext_pending(b):
    raw = b.call("rawPending")
    for marker in MARKERS + ["numero_de_cuba", "masa_humeda_g", "Laboratorio de Calidad", "source_draft_id"]:
        assert marker not in raw, "plaintext leaked into the pending store: " + marker
    return raw


with tempfile.TemporaryDirectory(prefix="vinto-off042-") as tmp, sync_playwright() as pw:
    # ---- 01 incomplete draft cannot transition; complete one does, atomically, frozen and isolated ----
    b = baseline(pw, tmp, "main")
    assert b.call("save", D1, {"numero_de_cuba": "C-001-SINT"}, None)["complete"] is False
    r = b.call("queue", D1, 1)
    assert r["ok"] is False and r["reason"] == "incomplete" and len(r["missing"]) == 6, r
    assert pending_rows(b) == [] and b.call("load", D1)["revision"] == 1
    assert b.call("save", D1, GOOD, 1)["revision"] == 2
    drafts_before = b.call("rawDrafts")
    r = b.call("queue", D1, 2)
    assert r["ok"] is True and r["created"] is True and r["sourceRevision"] == 2, r
    rows = pending_rows(b)
    assert len(rows) == 1
    row = rows[0]
    assert set(row) == {"capture_id", "draftId", "ownerId", "deviceKey", "formCode", "formVersion", "contextId",
                        "sourceRevision", "queuedAt", "status", "lab", "syncState", "sealed"}, set(row)
    assert row["status"] == "queued_local_simulation" and row["lab"] is True and row["syncState"] == "NOT_SYNCED"
    assert row["capture_id"] == r["captureId"] and row["draftId"] == D1 and row["sourceRevision"] == 2
    assert row["sealed"]["format"] == "aes-gcm-v1"
    no_plaintext_pending(b)
    assert b.call("rawDrafts") == drafts_before, "the source draft must stay byte-identical"
    assert b.call("realOutbox") == 0, "the application's send queue must stay empty"
    p = b.call("pendingLoad", D1)
    assert p["found"] and p["payload"]["status"] == "queued_local_simulation" and p["payload"]["sync_state"] == "NOT_SYNCED"
    assert p["payload"]["draft"]["values"]["masa_humeda_g"] == "120.50" and p["payload"]["draft"]["revision"] == 2
    assert p["payload"]["capture_id"] == r["captureId"] and p["payload"]["synthetic"] is True
    report("01_incomplete_refused_complete_transitions_frozen_isolated_encrypted")

    # ---- 02 immutability: no edits, no second pending, nothing changes ----
    snapshot = b.call("rawPending")
    r = b.call("save", D1, {**GOOD, "observaciones": "intento"}, 2)
    assert r["ok"] is False and r["reason"] == "pending_local", r
    r = b.call("save", D1, {**GOOD, "observaciones": "intento"}, 3)
    assert r["ok"] is False and r["reason"] == "pending_local", r
    again = b.call("queue", D1, 2)
    assert again["ok"] and again["created"] is False and again["captureId"] == row["capture_id"], again
    assert b.call("queue", D1, 1)["reason"] == "conflict"
    assert b.call("rawPending") == snapshot and b.call("rawDrafts") == drafts_before
    report("02_pending_is_immutable_and_repeat_transition_is_idempotent")
    b.kill()

    # ---- 03 stale revision: the draft moved on, the transition is refused without side effects ----
    b = baseline(pw, tmp, "stale-rev")
    assert b.call("save", D1, GOOD, None)["revision"] == 1
    assert b.call("save", D1, {**GOOD, "observaciones": "v2"}, 1)["revision"] == 2
    r = b.call("queue", D1, 1)
    assert r["ok"] is False and r["reason"] == "conflict", r
    assert pending_rows(b) == []
    assert b.call("queue", D2, 1)["reason"] == "not_found"
    assert b.call("queue", D1, 2)["created"] is True
    report("03_stale_revision_and_unknown_draft_are_refused")
    b.kill()

    # ---- 04 double click / retries inside one tab, and two tabs at once ----
    b = baseline(pw, tmp, "dup")
    assert b.call("save", D1, GOOD, None)["ok"] and b.call("save", D2, GOOD, None)["ok"]
    r = b.call("queueMany", D1, 1, 8)
    created = [x for x in r["results"] if x["ok"] and x["created"]]
    assert len(created) == 1 and all(x["ok"] and x["captureId"] == created[0]["captureId"] for x in r["results"]), r
    assert len(pending_rows(b)) == 1
    tab_b = b.new_tab()
    start = "([id]) => { window.__q = H.queue(id, 1); }"
    b.tab.page.evaluate(start, [D2]); tab_b.page.evaluate(start, [D2])
    ra = b.tab.page.evaluate("async () => await window.__q"); rb = tab_b.page.evaluate("async () => await window.__q")
    assert ra["ok"] and rb["ok"] and ra["captureId"] == rb["captureId"] and [ra["created"], rb["created"]].count(True) == 1, (ra, rb)
    assert len(pending_rows(b)) == 2 and len({x["draftId"] for x in pending_rows(b)}) == 2
    report("04_double_click_retries_and_two_tabs_create_exactly_one_pending")
    b.kill()

    # ---- 05 duplicate capture_id / duplicate draft are rejected by the store itself ----
    b = baseline(pw, tmp, "ids")
    assert b.call("save", D1, GOOD, None)["ok"] and b.call("save", D2, GOOD, None)["ok"]
    assert b.call("queue", D1, 1)["created"] is True
    base_row = pending_rows(b)[0]
    n = len(pending_rows(b))
    r = b.call("rawAddPending", {**base_row, "draftId": D2})                  # same capture_id, other draft
    assert r["ok"] is False and r["reason"] == "ConstraintError", r
    r = b.call("rawAddPending", {**base_row, "capture_id": "99999999-9999-4999-8999-999999999999"})   # same draft, other id
    assert r["ok"] is False and r["reason"] == "ConstraintError", r
    assert len(pending_rows(b)) == n
    assert pending_rows(b)[0] == base_row
    report("05_duplicate_capture_id_and_duplicate_draft_rejected_by_store")
    b.kill()

    # ---- 06 tampering is detected, damaged pendings are listed (never hidden, never modified) ----
    b = baseline(pw, tmp, "tamper")
    for d in (D1, D2, D3, D4):
        assert b.call("save", d, GOOD, None)["ok"] and b.call("queue", d, 1)["created"] is True
    caps = {x["draftId"]: x["capture_id"] for x in pending_rows(b)}
    b.call("tamperPending", caps[D1], "ciphertext")
    b.call("tamperPending", caps[D2], "revision")
    b.call("tamperPending", caps[D3], "draft_id")
    b.call("tamperPending", caps[D4], "status")
    lst = b.call("pendingList")
    assert lst["ok"] and lst["malformed"] == 1, lst                                  # status != simulation: counted, not hidden
    by = {i["captureId"]: i for i in lst["items"]}
    assert len(by) == 3, by
    assert by[caps[D3]]["corrupt"] is True and by[caps[D3]]["reason"] == "corrupt"
    assert by[caps[D1]]["corrupt"] is True and by[caps[D1]]["reason"] == "locked"     # same AEAD failure as a wrong key
    assert by[caps[D2]]["corrupt"] is True and by[caps[D2]]["reason"] == "corrupt"
    assert caps[D4] not in by
    assert len(pending_rows(b)) == 4                                                  # nothing removed
    report("06_tampered_pendings_fail_closed_and_none_is_removed")
    b.kill()

    # ---- 07 identity: another user/key sees and does nothing ----
    b = baseline(pw, tmp, "ident")
    assert b.call("save", D1, GOOD, None)["ok"]
    assert b.call("queue", D1, 1)["created"] is True
    r = b.call("queue", D1, 1, OTHER)
    assert r["ok"] is False and r["reason"] == "invalid", r
    assert b.call("pendingList", OTHER)["items"] == []
    b.call("useForeignKey")
    lst = b.call("pendingList")
    assert lst["items"][0]["corrupt"] is True and lst["items"][0]["reason"] == "locked", lst
    assert b.call("unlock", SECRET) is True
    assert len(pending_rows(b)) == 1
    b.kill()
    other_browser = baseline(pw, tmp, "ident-other-browser")
    assert other_browser.call("pendingList")["items"] == [] and pending_rows(other_browser) == []
    other_browser.kill()
    report("07_other_identity_key_and_browser_see_and_create_nothing")

    # ---- 08 storage failures: no half state, draft keeps working ----
    b = baseline(pw, tmp, "faults")
    assert b.call("save", D1, GOOD, None)["ok"]
    drafts_before = b.call("rawDrafts")
    for label, arm, reason in (("quota", lambda: b.call("failAddOn", 1, "QuotaExceededError"), "quota"),
                               ("write error", lambda: b.call("failAddOn", 1), "storage"),
                               ("failure AFTER the add inside the transaction", lambda: b.call("failAddOn", 1, "DataError", True), "storage"),
                               ("sealing error", lambda: b.call("failEncryptOn", 1), "storage")):
        arm()
        r = b.call("queue", D1, 1)
        b.call("clearFaults")
        assert r["ok"] is False and r["reason"] == reason, (label, r)
        assert pending_rows(b) == [], label                      # atomic: nothing partial
        assert b.call("rawDrafts") == drafts_before, label       # draft intact and still a draft
    assert b.call("save", D1, {**GOOD, "observaciones": "sigue editable"}, 1)["revision"] == 2
    assert b.call("queue", D1, 2)["created"] is True              # recovers once the fault is gone
    assert b.call("realOutbox") == 0
    report("08_quota_and_storage_errors_leave_no_partial_state_and_keep_the_draft")
    b.kill()

    # ---- 09 restart: pendings survive closing the browser, offline-style, and stay immutable ----
    b = baseline(pw, tmp, "restart")
    assert b.call("save", D1, GOOD, None)["ok"]
    cap = b.call("queue", D1, 1)["captureId"]
    b.kill()
    b.open()
    lst = b.call("pendingList")
    assert lst["ok"] and len(lst["items"]) == 1 and lst["items"][0]["captureId"] == cap and lst["items"][0]["corrupt"] is False, lst
    assert b.call("save", D1, GOOD, 1)["reason"] == "pending_local"
    again = b.call("queue", D1, 1)
    assert again["ok"] and again["created"] is False and again["captureId"] == cap
    assert b.call("pendingLoad", D1)["payload"]["draft"]["values"]["numero_de_cuba"] == "C-001-SINT"
    report("09_pending_survives_restart_and_stays_immutable")

    # ---- 10 definition change after queueing; new draft with the new version queues normally ----
    assert b.call("renewTo", FX["scope_v2"], FX["package_v2"])["ok"] is True
    assert b.call("save", D2, GOOD, None)["ok"]
    assert b.call("queue", D2, 1)["created"] is True
    assert b.call("pendingLoad", D2)["payload"]["draft"]["form_version"] == 2
    assert b.call("pendingLoad", D1)["payload"]["draft"]["form_version"] == 1      # the old pending is untouched
    b.kill()
    b = baseline(pw, tmp, "stale-def")
    assert b.call("save", D1, GOOD, None)["ok"]
    assert b.call("renewTo", FX["scope_v2"], FX["package_v2"])["ok"] is True
    r = b.call("queue", D1, 1)
    assert r["ok"] is False and r["reason"] == "stale_definition", r
    assert pending_rows(b) == []
    report("10_definition_change_never_requeues_or_rewrites_old_drafts")
    b.kill()

    # ---- 11 non-lab definition and no network, no send queue, ever ----
    b = Browser(pw, Path(tmp) / "nonlab")
    b.open(unlock=False)
    b.call("enrol", ID, SECRET)
    assert b.call("unlock", SECRET) is True
    assert b.call("seedNonLab", FX["non_lab_scope"], FX["non_lab_package"])["reason"] == "ineligible"
    assert pending_rows(b) == []
    b.kill()
    b = baseline(pw, tmp, "net")
    assert b.call("save", D1, GOOD, None)["ok"]
    b.call("queue", D1, 1); b.call("queue", D1, 1); b.call("pendingList"); b.call("pendingLoad", D1)
    assert b.call("networkAttempts") == [], b.call("networkAttempts")
    assert b.call("realOutbox") == 0
    assert all(u.startswith(URL.rstrip("/")) or u.startswith("data:") or u.startswith("about:") for u in requests_seen), \
        [u for u in requests_seen if not u.startswith(URL.rstrip("/"))]
    assert not any("/api/" in u for u in requests_seen)
    report("11_non_synthetic_refused_no_network_write_and_application_send_queue_empty")
    b.kill()
print("OFF04_2_QUEUE_INDEXEDDB_CHROME=PASS", flush=True)
