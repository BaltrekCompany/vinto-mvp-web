#!/usr/bin/env python3
"""OFF-04.5A real-Chrome END-TO-END: offline Quality capture -> encrypted draft -> local pending -> sync engine -> isolated FastAPI receiver.

Synthetic data only. The receiver is the DISPOSABLE test server (backend/tests/off044_receiver_server.py) on loopback, backed by a
throwaway PostgreSQL *_test database (OFF044_PG_URL in CI, or a user-space instance locally). Requires the dev server built with
OFFLINE_DRAFT_LAB=1. Browser requests may only go to the dev server and the loopback receiver; no real API is ever contacted.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright
from off03b3_fixture import USER_ID
from off03c4_fixture import pair, scope
from off04_fixture import FORM_P122, lab_package_p122

BASE = os.environ["OFF04_BASE_URL"]
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
STORE = os.environ.get("OFF05A_STORE", "pg")
SECRET = "VINTO OFF045A e2e synthetic secret 9027!!"
ROOT = Path(__file__).resolve().parents[1]
OTHER = "22222222-2222-4222-8222-222222222222"


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


class Receiver:
    def __init__(self, db):
        self.proc = subprocess.Popen(
            [sys.executable, "tests/off044_receiver_server.py", "--db", db, "--store", STORE, "--cors-origin", BASE.rstrip("/")],
            cwd=ROOT / "backend", stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line = ""
        deadline = time.time() + 60
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("PORT="):
                break
        assert line.startswith("PORT="), "receiver did not start"
        self.url = "http://127.0.0.1:" + line.strip().split("=")[1]

    def get(self, path):
        return json.loads(urllib.request.urlopen(self.url + path, timeout=10).read())

    def config(self, body):
        req = urllib.request.Request(self.url + "/__test__/config", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        return json.loads(urllib.request.urlopen(req, timeout=10).read())

    def receipts(self):
        return self.get("/__test__/receipts")

    def deliveries(self, capture_id):
        """POSTs that REACHED the server for this capture (first receipt + duplicates), from its append-only event log."""
        return len([e for e in self.get("/__test__/events") if e["capture_id"] == capture_id and e["kind"] in ("received", "duplicate")])

    def stop(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def expected_capture_id(owner, device, draft):
    """Same derivation as captureIdFor (OFF-04.2): the capture_id is stable and derived from owner+browser+draft."""
    b = bytearray(hashlib.sha256(":".join(["VINTO:OFF042:CAPTURE:v1", owner.lower(), device.lower(), draft.lower()]).encode()).digest()[:16])
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def launch(pw, profile):
    kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
    return pw.chromium.launch_persistent_context(user_data_dir=str(profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
                                                 service_workers="allow", **kwargs)


with tempfile.TemporaryDirectory(prefix="vinto-off045a-") as tmp, sync_playwright() as pw:
    rx = Receiver(os.path.join(tmp, "receipts.sqlite"))
    try:
        origin = BASE.rstrip("/")
        LAB = BASE.rstrip("/") + "/offline-e2e-lab.html?receiver=" + rx.url
        cors = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
        api_calls, seen, posts = [], [], []
        state = {"mode": "pass", "snapshot": None}
        db = rx.get("/__test__/db")
        if STORE == "pg":
            assert db["engine"] == "postgresql" and db["database"].endswith("_test"), db
        print("RECEIVER_STORE=" + json.dumps(db), flush=True)
        rx.config({"grants": [[USER_ID, "MP1", FORM_P122]], "context_default": "same", "fail_next": 0})

        def install(page):
            def mock(route):
                url = route.request.url
                api_calls.append(route.request.method + " " + url.split("/api/")[-1])
                if route.request.method == "OPTIONS":
                    route.fulfill(status=204, headers=cors)
                    return
                if "/api/auth/me" in url:
                    data = {"user": {"id": USER_ID, "username": "synthetic.quality", "display_name": "Synthetic Quality",
                                     "profiles": ["CALIDAD"], "permissions": ["quality.capture"], "must_change": False}}
                elif "/api/offline/quality-package" in url:
                    data = lab_package_p122(json.loads(route.request.post_data)["signed_scope"], 1)
                elif "/api/offline/scope" in url:
                    sc = scope("off045a", "2026-11-18T12:00:00Z", [pair("MP1", FORM_P122, 1)], device=json.loads(route.request.post_data)["device_key"])
                    state["snapshot"] = sc["payload"]["snapshot_id"]
                    data = sc
                else:
                    raise AssertionError("Unexpected URL: " + url)
                route.fulfill(status=200, headers={"Content-Type": "application/json", "Cache-Control": "no-store", **cors}, body=json.dumps(data, ensure_ascii=False))
            for endpoint in ("/api/auth/me", "/api/offline/scope", "/api/offline/quality-package"):
                page.route("**" + endpoint, mock)

        def receiver_route(ctx):
            def handler(route):
                req = route.request
                if req.method == "POST":
                    posts.append(json.loads(req.post_data)["capture_id"])
                mode = state["mode"]
                if req.method == "POST" and mode == "drop":
                    posts.pop()
                    route.abort("connectionfailed")
                elif req.method == "POST" and mode == "lose_response":
                    route.fetch()                       # the server really processes and persists the request ...
                    route.abort("connectionreset")      # ... but the browser never receives the answer
                else:
                    route.continue_()
            ctx.route(rx.url + "/**", handler)

        def open_lab(ctx, offline=False):
            ctx.set_offline(offline)
            page = ctx.new_page()
            page.set_default_timeout(60000)
            page.on("request", lambda r: seen.append(r.url))
            install(page)
            assert page.goto(LAB, wait_until="domcontentloaded", timeout=60000).status == 200
            page.get_by_text("Perfil local encontrado.", exact=False).wait_for()
            return page

        def unlock(page, secret=SECRET):
            page.locator("#e2e-unlock-secret").fill(secret)
            page.locator("#e2e-confirm").check()
            page.locator("#e2e-unlock-submit").click()

        def fill(page, key, value):
            page.locator("#f-" + key).fill(value)

        def new_capture(page, cuba, *, complete=True, convert=True, bridge=True):
            page.locator("#e2e-new").click()
            page.locator("#f-numero_de_cuba").wait_for()
            fill(page, "numero_de_cuba", cuba)
            if complete:
                fill(page, "masa_humeda", "12,5"); fill(page, "grado_de_refinacion_sr", "35.2"); fill(page, "amperaje", "88")
            page.locator("#e2e-save").click()
            page.get_by_text("Guardado localmente (borrador cifrado", exact=False).last.wait_for()
            draft_id = page.locator("#e2e-editor").get_attribute("data-draft-id")
            if convert:
                page.locator("#e2e-queue").click()
                page.wait_for_function("(id) => document.querySelector(`#e2e-captures li[data-draft-id='${id}']`)?.dataset.stage === 'pending'", arg=draft_id)
                if bridge:
                    page.locator(f"#e2e-captures li[data-draft-id='{draft_id}'] button.bridge").click()
                    page.wait_for_function("(id) => document.querySelector(`#e2e-captures li[data-draft-id='${id}']`)?.dataset.stage === 'queued'", arg=draft_id)
            return draft_id

        def stage(page, draft_id):
            return page.locator(f"#e2e-captures li[data-draft-id='{draft_id}']").get_attribute("data-stage")

        def wait_stage(page, draft_id, expected):
            page.wait_for_function("([id, st]) => document.querySelector(`#e2e-captures li[data-draft-id='${id}']`)?.dataset.stage === st", arg=[draft_id, expected])

        def capture_id(page, draft_id):
            return page.locator(f"#e2e-captures li[data-draft-id='{draft_id}']").get_attribute("data-captureId") or \
                page.locator(f"#e2e-captures li[data-draft-id='{draft_id}']").get_attribute("data-capture-id")

        def sync(page):
            page.locator("#e2e-sync-now").click()
            page.get_by_text("Sincronización con el receptor de prueba finalizada", exact=False).or_(page.get_by_text("sincronización pausada", exact=False)).or_(
                page.get_by_text("Pausada", exact=False)).or_(page.get_by_text("se interrumpió", exact=False)).or_(page.get_by_text("Ninguna captura se reasigna", exact=False)).first.wait_for()

        def receipts_for(ids):
            return [r for r in rx.receipts() if r["capture_id"] in ids]

        profile = Path(tmp) / "browser"
        # ---- 01 online preparation of the synthetic profile, scope and P1-22 package ----
        ctx = launch(pw, profile)
        receiver_route(ctx)
        prep = ctx.new_page()
        prep.set_default_timeout(90000)
        install(prep)
        prep.goto(BASE + "/offline-preparacion", wait_until="domcontentloaded", timeout=120000)
        prep.get_by_text("Preparación de prueba: crea una clave local protegida", exact=False).wait_for()
        prep.locator('input[type="password"]').nth(0).fill(SECRET)
        prep.locator('input[type="password"]').nth(1).fill(SECRET)
        prep.get_by_role("button", name="Preparar perfil local").click()
        prep.get_by_text("Perfil preparado", exact=False).wait_for()
        prep.get_by_placeholder("MP1, MP3").fill("MP1")
        prep.locator('input[type="password"]').fill(SECRET)
        prep.get_by_role("button", name="Guardar alcance firmado cifrado").click()
        prep.get_by_text("Alcance firmado verificado y guardado cifrado.", exact=False).wait_for()
        prep.get_by_placeholder("MP1", exact=True).fill("MP1")
        prep.get_by_placeholder("VINTO-P1-22").fill(FORM_P122)
        prep.locator('input[type="password"]').fill(SECRET)
        prep.get_by_role("button", name="Guardar formulario firmado cifrado").click()
        prep.get_by_text("Definición completa de Calidad firmada y guardada cifrada.", exact=False).wait_for()
        prep.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller", timeout=60000)
        # first visit ONLINE so the lab page caches itself for offline use
        warm = open_lab(ctx)
        warm.wait_for_function("async () => (await caches.open('vinto-off045lab-v1').then(c => c.keys())).length === 2", timeout=60000)
        warm.close(); prep.close()
        api_calls.clear()
        report("01_online_preparation_profile_scope_and_synthetic_p1_22_package")

        # ---- 02/03 OFFLINE: open the form, capture, validate, incomplete draft, pending, bridge ----
        page = open_lab(ctx, offline=True)
        assert "DATOS SINTÉTICOS" in page.locator(".lab").inner_text() and "NO es aprobación industrial" in page.locator(".lab").inner_text()
        unlock(page, "frase incorrecta 123456789!!")
        page.get_by_text("No fue posible desbloquear", exact=False).wait_for()
        unlock(page)
        page.get_by_text("Laboratorio desbloqueado (perfil original)", exact=False).wait_for()
        A = new_capture(page, "C-A-SINT")
        assert stage(page, A) == "queued" and "Pendiente de sincronización" in page.locator(f"#e2e-captures li[data-draft-id='{A}']").inner_text()
        # incomplete draft: saved locally, cannot become a pending, stays a draft
        page.locator("#e2e-new").click(); page.locator("#f-numero_de_cuba").wait_for()
        fill(page, "numero_de_cuba", "C-B-INCOMPLETA"); fill(page, "masa_humeda", "abc")
        page.locator("#e2e-save").click()
        page.get_by_text("NO se guardó: corrija los campos marcados.", exact=False).wait_for()
        assert page.locator("#err-masa_humeda").inner_text() == "valor no válido para el tipo"
        fill(page, "masa_humeda", "10")
        page.locator("#e2e-save").click()
        page.get_by_text("incompleto, faltan 2 obligatorio(s)", exact=False).wait_for()
        B = page.locator("#e2e-editor").get_attribute("data-draft-id")
        page.locator("#e2e-queue").click()
        page.get_by_text("faltan campos obligatorios", exact=False).wait_for()
        assert stage(page, B) == "draft" and "aún NO es un pendiente" in page.locator(f"#e2e-captures li[data-draft-id='{B}']").inner_text()
        assert rx.receipts() == []
        report("02_offline_form_validation_incomplete_draft_pending_and_explicit_bridge")

        # ---- 04 close the browser, reopen OFFLINE, unlock the original profile, recover everything ----
        ctx.close()
        ctx = launch(pw, profile)
        receiver_route(ctx)
        page = open_lab(ctx, offline=True)
        unlock(page)
        page.get_by_text("Laboratorio desbloqueado (perfil original)", exact=False).wait_for()
        assert stage(page, A) == "queued" and stage(page, B) == "draft"
        assert "queued=1" in page.locator("#e2e-counters").inner_text() and "borradores=1" in page.locator("#e2e-counters").inner_text()
        page.locator(f"#e2e-captures li[data-draft-id='{A}'] button.open").click()
        page.get_by_text("CONTENIDO CONGELADO", exact=False).first.wait_for()
        assert page.locator("#f-numero_de_cuba").input_value() == "C-A-SINT" and page.locator("#f-masa_humeda").input_value() == "12.5"
        assert page.locator("#f-numero_de_cuba").is_disabled()
        sync(page)                                                           # still offline: the engine cannot reach the receiver
        assert stage(page, A) == "retry_wait" and rx.receipts() == []
        report("03_close_reopen_offline_unlock_original_profile_and_recover_pendings")

        # ---- 05 reconnect + successful sync + single confirmation ----
        ctx.set_offline(False)
        page.locator("#e2e-clock").click()
        sync(page)
        wait_stage(page, A, "synced")
        rec = receipts_for({capture_id(page, A)})
        assert len(rec) == 1 and rec[0]["outcome"] == "accepted" and rec[0]["author"] == USER_ID, rec
        li = page.locator(f"#e2e-captures li[data-draft-id='{A}']").inner_text()
        assert "NO es aprobación industrial" in li and "servidor srv-" in li
        device = page.evaluate("() => localStorage.getItem('vinto-device-key')")
        assert device and capture_id(page, A) == expected_capture_id(USER_ID, device, A), "capture_id must be the stable derivation of owner+browser+draft"
        assert rx.deliveries(capture_id(page, A)) == 1
        report("04_reconnect_sync_success_and_single_confirmation_in_postgres")

        # ---- 06/07 response lost after persistence; retry without duplicates ----
        C = new_capture(page, "C-C-SINT")
        state["mode"] = "lose_response"
        sync(page)
        wait_stage(page, C, "retry_wait")
        cid = capture_id(page, C)
        assert len(receipts_for({cid})) == 1 and rx.deliveries(cid) == 1, "the server persisted it although the response was lost"
        assert "incierto" in page.locator(f"#e2e-captures li[data-draft-id='{C}']").inner_text()
        state["mode"] = "pass"
        page.locator("#e2e-clock").click()
        sync(page)
        wait_stage(page, C, "synced")
        assert len(receipts_for({cid})) == 1 and rx.deliveries(cid) == 1, "reconciled by GET: no second POST"
        report("05_lost_response_after_persistence_reconciled_without_duplicate")

        # ---- 08 network interruption keeps the pending and sends nothing ----
        D = new_capture(page, "C-D-SINT")
        state["mode"] = "drop"
        sync(page)
        wait_stage(page, D, "retry_wait")
        did = capture_id(page, D)
        assert receipts_for({did}) == [], "nothing reached the server"
        assert "intentos 1" in page.locator(f"#e2e-captures li[data-draft-id='{D}']").inner_text()
        state["mode"] = "pass"
        page.locator("#e2e-clock").click()
        sync(page)
        wait_stage(page, D, "synced")
        assert len(receipts_for({did})) == 1
        report("06_network_interruption_keeps_the_pending_then_syncs_once")

        # ---- 09/10 other authenticated user and expired session pause everything ----
        E = new_capture(page, "C-E-SINT")
        before = len(rx.receipts())
        page.locator("#e2e-session").select_option("other"); sync(page)
        page.get_by_text("sesión en línea es de otro usuario", exact=False).first.wait_for()
        assert stage(page, E) == "queued" and len(rx.receipts()) == before
        page.locator("#e2e-session").select_option("expired"); sync(page)
        page.get_by_text("No hay sesión en línea válida", exact=False).first.wait_for()
        assert stage(page, E) == "queued" and len(rx.receipts()) == before
        page.locator("#e2e-session").select_option("valid"); sync(page)
        wait_stage(page, E, "synced")
        assert len(rx.receipts()) == before + 1
        report("07_other_user_and_expired_session_pause_without_changes_then_original_author_syncs")

        # ---- 11/12/13 context changed (warning), review, rejected ----
        snap = state["snapshot"]
        assert snap
        F = new_capture(page, "C-F-SINT")
        rx.config({"context": {snap: "compatible_change"}}); sync(page); wait_stage(page, F, "synced_warning")
        assert "advertencia: context_changed_after_prepare" in page.locator(f"#e2e-captures li[data-draft-id='{F}']").inner_text()
        G = new_capture(page, "C-G-SINT")
        rx.config({"context": {snap: "incompatible_change"}}); sync(page); wait_stage(page, G, "requires_review")
        Hh = new_capture(page, "C-H-SINT")
        rx.config({"context": {snap: "unknown_form_version"}}); sync(page); wait_stage(page, Hh, "conflict")
        rx.config({"context": {snap: "same"}})
        outcomes = {r["capture_id"]: r["outcome"] for r in rx.receipts()}
        assert [outcomes[capture_id(page, x)] for x in (F, G, Hh)] == ["accepted_warning", "review", "conflict"]
        before = len(rx.receipts())
        sync(page)                                                           # terminal states are never retried
        assert len(rx.receipts()) == before and stage(page, G) == "requires_review" and stage(page, Hh) == "conflict"
        report("08_context_changed_warning_review_and_rejected_capture")

        # ---- 14 two simultaneous tabs: one logical capture, one POST ----
        tab2 = open_lab(ctx)
        unlock(tab2)
        tab2.get_by_text("Laboratorio desbloqueado (perfil original)", exact=False).wait_for()
        Ii = new_capture(page, "C-I-SINT")
        tab2.reload(); unlock(tab2)
        tab2.get_by_text("Laboratorio desbloqueado (perfil original)", exact=False).wait_for()
        assert stage(tab2, Ii) == "queued"
        iid = capture_id(page, Ii)
        page.locator("#e2e-sync-now").click(no_wait_after=True)
        tab2.locator("#e2e-sync-now").click(no_wait_after=True)
        wait_stage(page, Ii, "synced")
        tab2.reload(); unlock(tab2)
        wait_stage(tab2, Ii, "synced")
        assert len(receipts_for({iid})) == 1 and rx.deliveries(iid) == 1, (rx.deliveries(iid), receipts_for({iid}))
        tab2.close()
        report("09_two_simultaneous_tabs_send_once_and_register_once")

        # ---- 15 storage failure during synchronisation keeps every pending, recovers afterwards ----
        J = new_capture(page, "C-J-SINT")
        before = len(rx.receipts())
        page.evaluate("""() => { const orig = IDBObjectStore.prototype.put; window.__origPut = orig;
            IDBObjectStore.prototype.put = function (...a) { IDBObjectStore.prototype.put = orig; throw new DOMException('injected', 'QuotaExceededError'); }; }""")
        sync(page)
        page.get_by_text("error de almacenamiento", exact=False).first.wait_for()
        page.evaluate("() => { if (window.__origPut) IDBObjectStore.prototype.put = window.__origPut; }")
        page.evaluate("async () => 0")
        page.locator(f"#e2e-captures li[data-draft-id='{J}']").wait_for()
        assert stage(page, J) in ("queued", "syncing") and len(rx.receipts()) == before
        sync(page)
        wait_stage(page, J, "synced")
        assert len(rx.receipts()) == before + 1
        report("10_storage_failure_keeps_pendings_and_recovers")

        # ---- 16 final: exactly one logical capture per synced/reviewed capture; nothing else was contacted ----
        ids = [capture_id(page, x) for x in (A, C, D, E, F, G, Hh, Ii, J)]
        server_ids = [r["capture_id"] for r in rx.receipts()]
        assert sorted(server_ids) == sorted(ids) and len(set(server_ids)) == len(server_ids), (server_ids, ids)
        assert all(rx.deliveries(i) == 1 for i in ids), [(i, rx.deliveries(i)) for i in ids]   # every capture reached the server exactly once
        assert stage(page, B) == "draft"                                       # the incomplete draft was never lost nor sent
        ok_origins = (BASE.rstrip("/"), rx.url)
        stray = [u for u in seen if not (u.startswith(ok_origins) or u.startswith(("data:", "about:", "blob:")))]
        assert stray == [], stray
        assert [c for c in api_calls if not c.startswith("OPTIONS")] == [], api_calls
        report("11_one_logical_capture_each_no_stray_requests_and_nothing_lost")
        ctx.close()
    finally:
        rx.stop()
print("OFF04_5A_QUALITY_E2E=PASS", flush=True)
