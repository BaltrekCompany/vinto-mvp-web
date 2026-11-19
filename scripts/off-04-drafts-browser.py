#!/usr/bin/env python3
"""OFF-04.1 real-Chrome IndexedDB integration for encrypted LABORATORY drafts (synthetic data only).

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


with tempfile.TemporaryDirectory(prefix="vinto-off04-") as tmp, sync_playwright() as pw:
    # ---- 01 create, edit, save encrypted; incomplete vs complete ----
    b = baseline(pw, tmp, "main")
    r = b.call("save", D1, {"numero_de_cuba": "C-001-SINT"}, None)
    assert r["ok"] is True and r["revision"] == 1 and r["complete"] is False and len(r["missingRequired"]) == 6, r
    r = b.call("save", D1, GOOD, 1)
    assert r["ok"] is True and r["revision"] == 2 and r["complete"] is True and r["missingRequired"] == [], r
    d = b.call("load", D1)
    assert d["ok"] and d["revision"] == 2 and d["values"]["masa_humeda_g"] == "120.50" and d["values"]["muestra_valida"] is True, d
    p = d["payload"]
    assert p["status"] == "draft" and p["synthetic"] is True and p["author_user_id"] == ID["ownerId"].lower(), p
    assert p["machine_code"] == "MP1" and p["form_code"] == "VINTO-P1-26" and p["form_version"] == 1 and len(p["definition_sha256"]) == 64, p
    assert "consistencia_pct" not in p["values"]
    lst = b.call("list")
    assert lst["ok"] and len(lst["items"]) == 1 and lst["items"][0]["revision"] == 2 and lst["items"][0]["corrupt"] is False, lst
    raw = no_plaintext(b)
    row = json.loads(raw)[0]
    assert set(row) == {"id", "ownerId", "deviceKey", "formCode", "formVersion", "contextId", "savedAt", "revision", "sealed"}, set(row)
    assert row["sealed"]["format"] == "aes-gcm-v1" and b.call("rawOutboxCount") == 0
    report("01_create_edit_save_encrypted_no_plaintext_no_outbox")

    # ---- 02 validation: nothing invalid is ever stored ----
    for label, values in (("bad decimal", {"masa_seca_g": "abc"}), ("bad option", {"tipo_pasta": "inventada"}),
                          ("calculated field", {"consistencia_pct": "25.00"}), ("unknown key", {"x": "y"}),
                          ("bad date", {"fecha_muestreo": "2026-02-30"})):
        before = b.call("rawDrafts")
        r = b.call("save", D2, values, None)
        assert r["ok"] is False and r["reason"] == "invalid" and r["issues"], (label, r)
        assert b.call("rawDrafts") == before, label
    assert b.call("save", D1, {"numero_de_cuba": "otro"}, 1)["reason"] == "conflict"       # stale revision (current is 2)
    report("02_invalid_types_options_and_calculated_fields_are_never_saved")

    # ---- 03 restart offline-style: reopen the same profile, unlock, recover ----
    b.kill()
    b.open()
    d = b.call("load", D1)
    assert d["ok"] and d["revision"] == 2 and d["values"]["numero_de_cuba"] == "C-001-SINT", d
    assert len(b.call("list")["items"]) == 1
    assert b.call("save", D1, {**GOOD, "observaciones": "tras reinicio"}, 2)["revision"] == 3
    report("03_drafts_recovered_after_close_and_reopen")

    # ---- 04 wrong passphrase and tampered ciphertext ----
    assert b.call("unlock", "frase incorrecta 123456789!!") is False
    b.call("useForeignKey")
    d = b.call("load", D1)
    assert d["ok"] is False and d["reason"] == "locked", d
    lst = b.call("list")
    assert lst["ok"] and lst["items"][0]["corrupt"] is True and lst["items"][0]["reason"] == "locked", lst
    assert b.call("unlock", SECRET) is True
    r = b.call("save", D2, {"numero_de_cuba": "segundo"}, None)
    assert r["ok"] and r["revision"] == 1
    b.call("tamper", D2, "ciphertext")
    assert b.call("load", D2)["reason"] == "locked"
    lst = b.call("list")
    assert {i["id"]: i["corrupt"] for i in lst["items"]} == {D1: False, D2: True}, lst          # only the damaged one
    assert b.call("load", D1)["ok"] is True
    b.call("tamper", D1, "outer_revision")
    assert b.call("load", D1)["reason"] == "corrupt"
    b.call("tamper", D1, "drop_revision")
    assert b.call("load", D1)["reason"] == "corrupt"
    report("04_wrong_key_and_tampered_data_fail_closed_without_hiding_other_drafts")
    b.kill()

    # ---- 05 other identity, 06 isolated browsers ----
    b = baseline(pw, tmp, "iso")
    assert b.call("save", D1, GOOD, None)["ok"]
    r = b.call("save", D2, {"numero_de_cuba": "x"}, None, OTHER)         # another user cannot draft against this package
    assert r["ok"] is False and r["reason"] == "invalid", r
    assert b.call("list", OTHER) == {"ok": True, "items": []}
    assert b.call("load", D1, OTHER)["reason"] == "not_found"
    report("05_other_identity_sees_and_writes_nothing")
    b.kill()
    other_browser = baseline(pw, tmp, "iso-other-browser")
    assert other_browser.call("list") == {"ok": True, "items": []}
    assert other_browser.call("load", D1)["reason"] == "not_found"
    other_browser.kill()
    report("06_independent_browsers_do_not_share_drafts")

    # ---- 07 full storage and generic failures never report a save ----
    b = baseline(pw, tmp, "quota")
    assert b.call("save", D1, GOOD, None)["revision"] == 1
    before = b.call("rawDrafts")
    for label, arm, reason in (("quota", lambda: b.call("failPutOn", 1, "QuotaExceededError"), "quota"),
                               ("write error", lambda: b.call("failPutOn", 1), "storage"),
                               ("sealing error", lambda: b.call("failEncryptOn", 1), "storage")):
        arm()
        r = b.call("save", D1, {**GOOD, "observaciones": "no debe guardarse"}, 1)
        b.call("clearFaults")
        assert r["ok"] is False and r["reason"] == reason, (label, r)
        assert b.call("rawDrafts") == before, label
        assert b.call("load", D1)["revision"] == 1
    assert b.call("save", D1, {**GOOD, "observaciones": "ahora sí"}, 1)["revision"] == 2        # revision not consumed by failures
    b.call("failPutOn", 1, "QuotaExceededError")
    r = b.call("save", D2, GOOD, None)                                                           # brand-new draft, storage full
    b.call("clearFaults")
    assert r["ok"] is False and r["reason"] == "quota" and b.call("load", D2)["reason"] == "not_found"
    report("07_storage_full_and_write_failures_never_report_a_save")
    b.kill()

    # ---- 08 two tabs cannot silently overwrite a newer revision ----
    b = baseline(pw, tmp, "tabs")
    b.call("save", D1, {**GOOD, "observaciones": "base"}, None)
    tab_b = b.new_tab()
    a_view, b_view = b.call("load", D1), tab_b.call("load", D1)
    assert a_view["revision"] == b_view["revision"] == 1
    assert b.call("save", D1, {**GOOD, "observaciones": "de la pestaña A"}, 1)["revision"] == 2
    r = tab_b.call("save", D1, {**GOOD, "observaciones": "de la pestaña B"}, 1)
    assert r["ok"] is False and r["reason"] == "conflict", r
    assert b.call("load", D1)["values"]["observaciones"] == "de la pestaña A"                     # A's newer version survived
    fresh = tab_b.call("load", D1)
    assert tab_b.call("save", D1, {**GOOD, "observaciones": "B tras recargar"}, fresh["revision"])["revision"] == 3
    # same new id created concurrently from two tabs
    assert b.call("save", D2, {"numero_de_cuba": "A"}, None)["revision"] == 1
    assert tab_b.call("save", D2, {"numero_de_cuba": "B"}, None)["reason"] == "conflict"
    assert b.call("load", D2)["values"]["numero_de_cuba"] == "A"
    # the writer that wins the race COMMITS between the loser's read and its transaction (CAS inside the tx)
    r = b.call("raceSave", D1, {**GOOD, "observaciones": "perdedor"}, 3, {**GOOD, "observaciones": "ganador"})
    assert r["ok"] is False and r["reason"] == "conflict", r
    d = b.call("load", D1)
    assert d["revision"] == 4 and d["values"]["observaciones"] == "ganador", d
    report("08_two_tabs_conflict_never_overwrites_a_newer_revision")
    b.kill()

    # ---- 09 no central call, no queue, ever ----
    b = baseline(pw, tmp, "net")
    b.call("save", D1, GOOD, None)
    b.call("save", D1, GOOD, 1)
    b.call("list"); b.call("load", D1)
    assert b.call("networkAttempts") == [], b.call("networkAttempts")
    assert b.call("rawOutboxCount") == 0
    assert all(u.startswith(URL.rstrip("/")) or u.startswith("data:") or u.startswith("about:") for u in requests_seen), \
        [u for u in requests_seen if not u.startswith(URL.rstrip("/"))]
    assert not any("/api/" in u for u in requests_seen)
    report("09_no_network_write_call_and_no_queue_entry")
    b.kill()

    # ---- 10 definition change: old drafts stay readable and are never silently migrated ----
    b = baseline(pw, tmp, "stale")
    assert b.call("save", D1, GOOD, None)["revision"] == 1
    r = b.call("renewTo", FX["scope_v2"], FX["package_v2"])
    assert r["ok"] is True, r
    d = b.call("load", D1)
    assert d["ok"] and d["payload"]["form_version"] == 1 and d["revision"] == 1
    r = b.call("save", D1, {**GOOD, "observaciones": "x"}, 1)
    assert r["ok"] is False and r["reason"] == "stale_definition", r
    assert b.call("load", D1)["revision"] == 1
    assert b.call("save", D2, GOOD, None)["revision"] == 1         # a NEW draft uses the new definition
    assert b.call("load", D2)["payload"]["form_version"] == 2
    report("10_definition_change_keeps_old_draft_readonly_and_new_drafts_use_new_version")
    b.kill()

    # ---- 11 a real (non lab) definition is never editable here ----
    b = Browser(pw, Path(tmp) / "nonlab")
    b.open(unlock=False)
    b.call("enrol", ID, SECRET)
    assert b.call("unlock", SECRET) is True
    r = b.call("seedNonLab", FX["non_lab_scope"], FX["non_lab_package"])
    assert r["ok"] is False and r["reason"] == "ineligible", r
    assert b.call("rawDrafts") == "[]"
    report("11_non_synthetic_definition_refused")
    b.kill()
print("OFF04_DRAFTS_INDEXEDDB_CHROME=PASS", flush=True)
