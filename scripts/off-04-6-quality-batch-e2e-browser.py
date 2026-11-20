#!/usr/bin/env python3
"""OFF-04.6 real-Chrome END-TO-END for the ten Quality forms (by machine: P1-18/22/26/27; by bobbin: P1-19/20/21/24/25/28).

One origin: the QA pilot app exactly as the real entrypoint builds it (backend/tests/off0506b_server.py --forms all) over a throwaway PostgreSQL, serving the opt-in lab build.
Per form: online device preparation (signed scope + ten signed packages), bobbin context prepared online for by-bobbin forms, OFFLINE capture, encrypted draft, pending, restart
without internet, reconnect, sync with the original author, ONE receipt, the SERVER-computed calculations, duplicates, central validation on bad content, capture preserved.
Everything synthetic; no deployed service is ever contacted.  Requires the lab built with OFFLINE_DRAFT_LAB=1 into ./public (env OFF06B_PUBLIC overrides).
"""
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.parse
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
ROOT = Path(__file__).resolve().parents[1]
PUBLIC = os.environ.get("OFF06B_PUBLIC", str(ROOT / "public"))
SECRET = "VINTO OFF046 e2e synthetic secret 5582!!"
BY_MACHINE = ("VINTO-P1-18", "VINTO-P1-22", "VINTO-P1-26", "VINTO-P1-27")
BY_BOBBIN = ("VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28")
FORMS = BY_MACHINE + BY_BOBBIN
BOBBIN = "B-0001-SINT"


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


class Server:
    def __init__(self):
        self.proc = subprocess.Popen([sys.executable, "tests/off0506b_server.py", "--public", PUBLIC, "--mode", "full", "--forms", "all"], cwd=ROOT / "backend",
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line, deadline = "", time.time() + 240
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("READY ") or not line:
                break
        assert line.startswith("READY "), "server did not start: " + line
        self.info = json.loads(line[len("READY "):])
        self.origin, self.users = self.info["origin"], self.info["users"]

    def get(self, path):
        return json.loads(urllib.request.urlopen(self.origin + path, timeout=30).read())

    def stop(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=60)
        except Exception:
            self.proc.kill()


def launch(pw, profile):
    kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
    return pw.chromium.launch_persistent_context(user_data_dir=str(profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], service_workers="allow", **kwargs)


with tempfile.TemporaryDirectory(prefix="vinto-off046-") as tmp, sync_playwright() as pw:
    srv = Server()
    try:
        LAB = srv.origin + "/offline-e2e-lab.html"
        A = srv.users["a"]
        info = srv.get("/__test__/info")
        assert info["version"].split(".")[0] in ("16", "17", "18") and info["app_role_identity_select"] is False, info
        print("RECEIVER_STORE=" + json.dumps({"engine": "postgresql", "version": info["version"]}), flush=True)
        profile = Path(tmp) / "main"
        ctx = launch(pw, profile)

        def open_lab(offline=False):
            ctx.set_offline(offline)
            page = ctx.new_page()
            page.set_default_timeout(60000)
            assert page.goto(LAB, wait_until="domcontentloaded", timeout=60000).status == 200
            st = page.locator("#e2e-auth-status")
            st.get_by_text("Sesión en línea", exact=False).or_(st.get_by_text("Sin sesión", exact=False)).or_(st.get_by_text("Sin conexión", exact=False)).first.wait_for()
            return page

        def say(page, text, timeout=60000):
            try:
                page.locator("#e2e-status").get_by_text(text, exact=False).first.wait_for(timeout=timeout)
            except Exception:
                print("STATUS WAS:", page.locator("#e2e-status").inner_text(), flush=True)
                raise

        def unlock(page):
            page.locator("#e2e-unlock-secret").fill(SECRET)
            page.locator("#e2e-confirm").check()
            page.locator("#e2e-unlock-submit").click()
            say(page, "Laboratorio desbloqueado (perfil original)")

        def pick_form(page, form):
            idx = page.evaluate("(f) => Array.from(document.querySelectorAll('#e2e-package option')).findIndex(o => o.textContent.includes(f))", form)
            assert idx >= 0, "package missing in the device: " + form
            page.locator("#e2e-package").select_option(index=idx)

        def fill_values(page, values):
            for key, value in values.items():
                el = page.locator("#f-" + key)
                if el.evaluate("e => e.tagName") == "SELECT":
                    el.select_option(("true" if value else "false") if isinstance(value, bool) else str(value))
                else:
                    el.fill(str(value))

        def stage(page, draft):
            return page.locator(f"#e2e-captures li[data-draft-id='{draft}']").get_attribute("data-stage")

        def wait_stage(page, draft, expected):
            try:
                page.wait_for_function("([id, st]) => document.querySelector(`#e2e-captures li[data-draft-id='${id}']`)?.dataset.stage === st", arg=[draft, expected], timeout=60000)
            except Exception:
                print("STAGE WANTED", expected, "| LI:", page.locator(f"#e2e-captures li[data-draft-id='{draft}']").inner_text(), "| STATUS:", page.locator("#e2e-status").inner_text(), flush=True)
                raise

        def capture(page, form, values, bobbin=None):
            pick_form(page, form)
            if form in BY_BOBBIN:
                page.locator("#e2e-bobbin").select_option(index=0)
            page.locator("#e2e-new").click()
            page.locator("#e2e-fields [data-key]").first.wait_for()
            fill_values(page, values)
            page.locator("#e2e-save").click()
            page.get_by_text("Guardado localmente (borrador cifrado", exact=False).last.wait_for()
            draft = page.locator("#e2e-editor").get_attribute("data-draft-id")
            page.locator("#e2e-queue").click()
            wait_stage(page, draft, "pending")
            page.locator(f"#e2e-captures li[data-draft-id='{draft}'] button.bridge").click()
            wait_stage(page, draft, "queued")
            return draft

        def sync(page):
            page.locator("#e2e-sync-now").click()
            st = page.locator("#e2e-status")
            st.get_by_text("finalizada", exact=False).or_(st.get_by_text("pausada", exact=False)).or_(st.get_by_text("Sin conexión", exact=False)).or_(
                st.get_by_text("se interrumpió", exact=False)).first.wait_for()

        # ---- 01 online: real login, prepare the device with the signed scope and ALL ten signed packages ----
        page = open_lab()
        page.locator("#e2e-login-user").fill(A["username"]); page.locator("#e2e-login-pass").fill(A["password"]); page.locator("#e2e-login-submit").click()
        page.wait_for_function("() => document.querySelector('#e2e-auth-status')?.dataset.state === 'ok'")
        page.locator("#e2e-prepare-machine").fill("MP1"); page.locator("#e2e-prepare-pass").fill(SECRET); page.locator("#e2e-prepare-submit").click()
        say(page, "Dispositivo preparado")
        unlock(page)
        offered = page.evaluate("() => Array.from(document.querySelectorAll('#e2e-package option')).map(o => o.textContent)")
        assert len(offered) == 10 and all(any(f in o for o in offered) for f in FORMS), offered
        assert all("SINTÉTICO" in o for o in offered), offered
        report("01_device_prepared_with_signed_scope_and_ten_signed_synthetic_packages")

        # ---- 02 online: the historical bobbin context is prepared and kept encrypted; machine forms never ask for a bobbin ----
        pick_form(page, "VINTO-P1-22")
        assert page.locator("#e2e-bobbin-box").is_hidden()
        pick_form(page, "VINTO-P1-19")
        assert page.locator("#e2e-bobbin-box").is_visible()
        page.locator("#e2e-new").click()
        say(page, "prepare (en línea) y seleccione una bobina")                 # no bobbin prepared yet: no draft can be started
        page.locator("#e2e-bobbin-code").fill("NO-EXISTE")
        page.locator("#e2e-bobbin-prepare").click()
        say(page, "No existe una bobina con ese número")
        page.locator("#e2e-bobbin-code").fill(BOBBIN)
        page.locator("#e2e-bobbin-prepare").click()
        say(page, "Contexto de bobina guardado cifrado")
        assert BOBBIN in page.locator("#e2e-bobbin").inner_text()
        report("02_bobbin_context_prepared_online_and_sealed_locally")
        page.close()

        # ---- 03 OFFLINE: one capture per form, valid synthetic content; calculated fields are read-only and say so ----
        page = open_lab(offline=True)
        unlock(page)
        expected, drafts = {}, {}
        for form in FORMS:
            data = srv.get("/__test__/values?form=" + form)
            expected[form] = data
            drafts[form] = capture(page, form, data["values"])
            assert stage(page, drafts[form]) == "queued", form
            for key in data["calculated"]:
                el = page.locator("#f-" + key)
                assert el.is_disabled() and (el.get_attribute("placeholder") or "").startswith("calculado por el servidor"), (form, key)
        assert srv.get("/__test__/receipts") == []                              # offline: nothing reached the server
        report("03_offline_capture_of_the_ten_forms_encrypted_pending_and_calculations_left_to_the_server")

        # ---- 04 restart without internet: every pending recovered, byte-frozen content ----
        ctx.close()
        ctx = launch(pw, profile)
        page = open_lab(offline=True)
        unlock(page)
        for form in FORMS:
            assert stage(page, drafts[form]) == "queued", form
        page.locator(f"#e2e-captures li[data-draft-id='{drafts['VINTO-P1-21']}'] button.open").click()
        page.get_by_text("CONTENIDO CONGELADO", exact=False).first.wait_for()
        assert page.locator("#f-gramaje_01").input_value() == "10.00"
        report("04_restart_without_internet_recovers_the_ten_pendings")

        # ---- 05 reconnect: the original author syncs; ONE accepted receipt per form with the SERVER-computed values ----
        ctx.set_offline(False)
        page.reload()
        unlock(page)
        page.locator("#e2e-auth-status").get_by_text("Sesión en línea", exact=False).wait_for()
        sync(page)
        cids = {}
        for form in FORMS:
            wait_stage(page, drafts[form], "synced")
            cid = page.locator(f"#e2e-captures li[data-draft-id='{drafts[form]}']").get_attribute("data-capture-id")
            cids[form] = cid
            r = srv.get("/__test__/receipt?capture_id=" + cid)
            assert r and r["outcome"] == "accepted", (form, r)
            assert r["body"].get("server_calculated", {}) == expected[form]["calculated"], (form, r["body"])
            assert srv.get("/__test__/events") and len([e for e in srv.get("/__test__/events") if e["capture_id"] == cid and e["kind"] in ("received", "duplicate")]) == 1, form
        rows = srv.get("/__test__/receipts")
        assert len(rows) == 10 and {x["author"] for x in rows} == {A["id"]}, rows
        report("05_sync_one_accepted_receipt_per_form_original_author_and_server_calculations")

        # ---- 06 syncing again creates nothing (idempotent) ----
        sync(page)
        assert len(srv.get("/__test__/receipts")) == 10
        report("06_second_sync_does_not_duplicate")

        # ---- 07 central validation: a bobbin form whose declared bobbin number differs from the prepared bobbin is NOT accepted; the capture is kept for review ----
        bad = dict(expected["VINTO-P1-28"]["values"]); bad["numero_de_bobina"] = "OTRA-BOBINA"
        d = capture(page, "VINTO-P1-28", bad)
        sync(page)
        wait_stage(page, d, "requires_review")
        cid = page.locator(f"#e2e-captures li[data-draft-id='{d}']").get_attribute("data-capture-id")
        r = srv.get("/__test__/receipt?capture_id=" + cid)
        assert r and r["outcome"] == "review" and any("bobbin_mismatch" in w for w in r["warnings"]), r
        assert "OTRA-BOBINA" not in json.dumps(r), "the rejected value is never echoed"
        assert page.locator(f"#e2e-captures li[data-draft-id='{d}']").count() == 1      # the capture is still on the device
        report("07_invalid_bobbin_content_is_kept_and_sent_to_review_never_accepted")

        # ---- 08 a draft for a by-bobbin form cannot start without a prepared bobbin of THAT machine; machine forms are unaffected ----
        pick_form(page, "VINTO-P1-22")
        page.locator("#e2e-new").click()
        page.locator("#f-numero_de_cuba").wait_for()
        report("08_machine_forms_never_require_a_bobbin")
        ctx.close()
        print("OFF04_6_CHROME_E2E=PASS", flush=True)
    finally:
        srv.stop()
