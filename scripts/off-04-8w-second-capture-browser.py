#!/usr/bin/env python3
"""OFF-04.8 v6.1 (Issue #249) REAL-Chrome test: the second capture of a session and the visual state after an AUTOMATIC sync, against the disposable loopback stub of off-04-8v
(real signer; no deployed service, DB or secret). Run it against the BASELINE build to REPRODUCE the defects (OFF048W_EXPECT=bug) and against the fixed build (OFF048W_EXPECT=fixed).
  - after a confirmed capture, "Guardar captura" of the NEXT editor must be enabled (bug: it stays disabled);
  - the queue list must show "Registrado en Calidad" after the AUTOMATIC acknowledgement, with no manual refresh (bug: it keeps saying "Pendiente");
  - drafts, the encrypted queue and confirmed captures are never lost or unlocked; resume, form switch, offline -> online and a Chrome restart keep working.
Usage: OFF06B_PUBLIC=<operational build dir> OFF048W_EXPECT=bug|fixed [OFF04_CHROME_CHANNEL=bundled] python scripts/off-04-8w-second-capture-browser.py"""
import http.server, importlib.util, json, os, shutil, sys, tempfile, threading
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
spec = importlib.util.spec_from_file_location("off8v", HERE / "off-04-8v-reuse-browser.py"); V = importlib.util.module_from_spec(spec); spec.loader.exec_module(V)
PUBLIC = Path(os.environ.get("OFF06B_PUBLIC", str(HERE.parent / "public"))); EXPECT = os.environ.get("OFF048W_EXPECT", "fixed"); FIXED = EXPECT == "fixed"
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome"); SECRET = V.SECRET; res = []


def rep(name, cond, detail=""):
    res.append(bool(cond)); print(json.dumps({"case": name, "result": "PASS" if cond else "FAIL", "detail": str(detail)[:240]}), flush=True)


def info(name, value): print(json.dumps({"observed": name, "value": str(value)[:240]}), flush=True)


def make_handler(stub):
    Base = V.make_handler(stub)
    class H(Base):
        def do_POST(s):
            if s.path == "/api/offline/captures":
                b = s._body()
                with stub.lock:
                    stub.counts["captures"] = stub.counts.get("captures", 0) + 1
                    if not s._auth(): return s._json(401, {"detail": "no"})
                    if not getattr(stub, "captures_ok", True): return s._json(500, {"detail": "boom"})
                    return s._json(201, {"outcome": "created", "capture_id": b["capture_id"], "payload_sha256": b["payload_sha256"], "server_id": "srv-" + b["capture_id"][:8], "warnings": [],
                                         "technical_acceptance": True, "operational_registered": True, "operational_capture_id": b["capture_id"]})
            super().do_POST()
    return H


def main():
    tmp = Path(tempfile.mkdtemp(prefix="off048w-")); pub = tmp / "public"; pub.mkdir()
    for f in PUBLIC.iterdir():
        if f.is_file() and f.name != "SHA256SUMS": shutil.copy(f, pub / f.name)
    stub = V.Stub(pub); stub.captures_ok = True
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stub)); threading.Thread(target=srv.serve_forever, daemon=True).start(); origin = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as pw:
            kw = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
            def launch(): return pw.chromium.launch_persistent_context(user_data_dir=str(tmp / "profile"), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], service_workers="allow", **kw)
            ctx = launch()
            def open_page():
                p = ctx.new_page(); p.set_default_timeout(45000); p.goto(origin + "/offline-calidad.html", wait_until="load"); p.wait_for_timeout(800); return p
            def wait_ready(p, n): p.wait_for_function("n => document.getElementById('status').textContent.includes('(' + n + ' de ' + n + ')')", arg=n, timeout=60000)
            def drafts(p): return p.locator("#drafts").inner_text()
            def fill_editor(p, tag="1"):
                p.wait_for_selector("#editor:not([hidden])")
                for i in range(p.locator("#fields input, #fields select").count()):
                    c = p.locator("#fields input, #fields select").nth(i); t = c.evaluate("e => e.tagName + ':' + (e.type || '')")
                    if t.startswith("SELECT"): c.select_option(index=1)
                    elif t.endswith("checkbox"): c.check()
                    else: c.fill(tag)
                p.wait_for_timeout(300)
            def new_draft(p, form="VINTO-P1-22"):
                p.select_option("#form", value=p.evaluate("f => [...document.querySelectorAll('#form option')].findIndex(o => o.textContent.includes(f)).toString()", form)); p.click("#new"); p.wait_for_selector("#editor:not([hidden])")
            def save(p): p.click("#capture-save"); p.wait_for_selector("#workspace:not([hidden])"); p.wait_for_timeout(500)
            p = open_page()
            p.fill("#username", "qa.synthetic"); p.fill("#password", "synthetic-pass-0000"); p.click("#login button[type=submit]")
            p.wait_for_selector("#prepare-panel:not([hidden])"); p.fill("#machine", "MP1"); p.fill("#passphrase", SECRET); p.click("#prepare button[type=submit]"); wait_ready(p, 10)
            # ---- capture #1 online, automatic send
            new_draft(p); rep("editor 1 opens with an ENABLED Save button", p.locator("#capture-save").is_enabled()); fill_editor(p); save(p)
            p.wait_for_function("() => document.getElementById('drafts').textContent.includes('Registrado en Calidad')", timeout=12000) if FIXED else p.wait_for_timeout(7000)
            info("after capture 1 + automatic ACK, queue says", drafts(p).replace("\n", " | "))
            rep("capture 1 reached the server exactly once, automatically (no manual sync pressed)", stub.counts.get("captures") == 1, stub.counts.get("captures"))
            shown = "Registrado en Calidad" in drafts(p)
            rep("automatic ACK is VISIBLE in the queue without pressing anything" if FIXED else "BASELINE defect reproduced: ACK not shown until a manual refresh (list still says Pendiente)", shown if FIXED else (not shown and "Pendiente" in drafts(p)), drafts(p)[:120])
            # ---- capture #2 in the same session
            new_draft(p, "VINTO-P1-18" if False else "VINTO-P1-22")
            enabled = p.locator("#capture-save").is_enabled()
            rep("second editor: Save button ENABLED" if FIXED else "BASELINE defect reproduced: Save button DISABLED in the second editor", enabled if FIXED else (not enabled), enabled)
            if not FIXED:
                info("baseline: the form fields are editable while Save is disabled", p.locator("#fields input").first.is_editable())
            else:
                fill_editor(p, "2"); save(p); p.wait_for_timeout(2500)
                rep("capture 2 confirmed and delivered (2 requests, queue shows two registered)", stub.counts.get("captures") == 2 and drafts(p).count("Registrado en Calidad") == 2, drafts(p)[:200])
                # ---- confirmed captures stay immutable: no 'Continuar borrador' on them, no unlock
                rep("confirmed captures offer NO resume button (immutable)", p.locator("#drafts li button").count() == 0, p.locator("#drafts li button").count())
                # ---- resume an existing draft, values preserved, button enabled
                new_draft(p); fill_editor(p, "3"); p.wait_for_timeout(1500); p.click("#back"); p.wait_for_selector("#workspace:not([hidden])"); p.wait_for_timeout(700)
                rep("Volver keeps the draft (Borrador local + Continuar borrador)", "Borrador local" in drafts(p) and p.locator("#drafts li button").count() == 1, (p.locator("#drafts li button").count(), drafts(p)))
                p.locator("#drafts li button").first.click(); p.wait_for_selector("#editor:not([hidden])")
                rep("resumed draft: Save ENABLED and the typed value is restored", p.locator("#capture-save").is_enabled() and p.locator("#fields input").first.input_value() == "3", p.locator("#fields input").first.input_value())
                p.click("#back"); p.wait_for_selector("#workspace:not([hidden])"); p.wait_for_timeout(700)
                # ---- switch form
                new_draft(p, "VINTO-P1-18"); rep("other form: Save ENABLED", p.locator("#capture-save").is_enabled()); p.click("#back"); p.wait_for_selector("#workspace:not([hidden])"); p.wait_for_timeout(700)
                # ---- offline -> queued -> online -> automatic ACK visible
                ctx.set_offline(True); new_draft(p); fill_editor(p, "4"); save(p); p.wait_for_timeout(1000)
                rep("offline: capture queued as Pendiente, nothing sent", "Pendiente" in drafts(p) and stub.counts.get("captures") == 2, drafts(p)[:200])
                ctx.set_offline(False); p.evaluate("window.dispatchEvent(new Event('online'))")
                p.wait_for_function("() => (document.getElementById('drafts').textContent.match(/Registrado en Calidad/g) || []).length === 3", timeout=20000)
                rep("reconnection: the automatic pass delivers it and the list updates by itself", stub.counts.get("captures") == 3, stub.counts.get("captures"))
                # ---- transient server failure: stays pending, no loss, retries later
                stub.captures_ok = False; new_draft(p); fill_editor(p, "5"); save(p); p.wait_for_timeout(2500)
                rep("server 500: the capture stays queued (not lost, not duplicated)", "Registrado en Calidad" in drafts(p) and drafts(p).count("Registrado en Calidad") == 3 and ("Pendiente" in drafts(p) or "Reintento" in drafts(p) or "Sincronizando" in drafts(p)), drafts(p)[:240])
                stub.captures_ok = True
                # ---- Chrome restart: everything encrypted survives, new editor enabled
                p.close(); ctx.close(); ctx = launch(); p = open_page(); p.fill("#unlock-secret", SECRET); p.click("#unlock button[type=submit]"); p.wait_for_selector("#workspace:not([hidden])"); p.wait_for_timeout(3000)
                rep("after a Chrome restart the queue and drafts are still there", drafts(p).count("Registrado en Calidad") >= 3 and "No existen" not in drafts(p), drafts(p)[:240])
                n_before = drafts(p).count("\n")
                new_draft(p); rep("after the restart a NEW editor has Save ENABLED", p.locator("#capture-save").is_enabled()); p.click("#back"); p.wait_for_selector("#workspace:not([hidden])"); p.wait_for_timeout(700)
                rep("no entry was dropped by opening/closing editors", drafts(p).count("\n") >= n_before, (n_before, drafts(p).count("\n")))
            ctx.close()
    finally:
        srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
    print(f"OFF048W_BROWSER expect={EXPECT} checks={len(res)} fails={res.count(False)} stub={stub.counts}")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
