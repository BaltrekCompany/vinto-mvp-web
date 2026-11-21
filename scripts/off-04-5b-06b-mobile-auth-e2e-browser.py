#!/usr/bin/env python3
"""OFF-04.5B-06B real-Chrome END-TO-END: real login cookie -> device preparation from the QA synthetic issuer -> offline Quality capture -> encrypted draft ->
local pending -> sync engine -> isolated QA receiver (FastAPI + disposable PostgreSQL, restricted application role, dedicated identity role).

Everything is synthetic. ONE origin serves the lab pages and the API (the pilot app exactly as the real entrypoint builds it, started by
backend/tests/off0506b_server.py on loopback). The browser only ever talks to that origin; no identity header exists, the identity is the real session cookie.
Requires the lab built with OFFLINE_DRAFT_LAB=1 into ./public (env OFF06B_PUBLIC overrides) and TEST_DATABASE_URL / TEST_ADMIN_DATABASE_URL for the disposable server.
"""
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from playwright.sync_api import sync_playwright

CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
ROOT = Path(__file__).resolve().parents[1]
PUBLIC = os.environ.get("OFF06B_PUBLIC", str(ROOT / "public"))
SECRET = "VINTO OFF06B e2e synthetic secret 4471!!"
SNAPSHOT = "55555555-5555-4555-8555-555555555555"
COOKIE = "vinto_qa_e2e"


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


class Server:
    def __init__(self, mode):
        self.proc = subprocess.Popen([sys.executable, "tests/off0506b_server.py", "--public", PUBLIC, "--mode", mode], cwd=ROOT / "backend",
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        line, deadline = "", time.time() + 180
        while time.time() < deadline:
            line = self.proc.stdout.readline()
            if line.startswith("READY ") or not line:
                break
        assert line.startswith("READY "), "server did not start: " + line
        self.info = json.loads(line[len("READY "):])
        self.origin, self.users = self.info["origin"], self.info["users"]

    def get(self, path):
        return json.loads(urllib.request.urlopen(self.origin + path, timeout=15).read())

    def request(self, method, path, *, headers=None, body=None):
        req = urllib.request.Request(self.origin + path, data=None if body is None else json.dumps(body).encode(), method=method, headers=headers or {})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def receipts(self):
        return self.get("/__test__/receipts")

    def deliveries(self, capture_id):
        """POSTs that REACHED the server for this capture (first receipt + duplicates), from its append-only event log."""
        return len([e for e in self.get("/__test__/events") if e["capture_id"] == capture_id and e["kind"] in ("received", "duplicate")])

    def stop(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=60)
        except Exception:
            self.proc.kill()


def expected_capture_id(owner, device, draft):
    """Same derivation as captureIdFor (OFF-04.2): stable and derived from owner+browser+draft."""
    b = bytearray(hashlib.sha256(":".join(["VINTO:OFF042:CAPTURE:v1", owner.lower(), device.lower(), draft.lower()]).encode()).digest()[:16])
    b[6] = (b[6] & 0x0F) | 0x40
    b[8] = (b[8] & 0x3F) | 0x80
    h = b.hex()
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:]}"


def launch(pw, profile):
    kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
    return pw.chromium.launch_persistent_context(user_data_dir=str(profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], service_workers="allow", **kwargs)


with tempfile.TemporaryDirectory(prefix="vinto-off06b-") as tmp, sync_playwright() as pw:
    srv = Server("full")
    try:
        origin = srv.origin
        LAB = origin + "/offline-e2e-lab.html"
        A, B = srv.users["a"], srv.users["b"]
        seen = []
        info = srv.get("/__test__/info")
        assert info["db"].endswith("_test") and info["version"].split(".")[0] in ("16", "17", "18") and info["app_role_identity_select"] is False, info
        print("RECEIVER_STORE=" + json.dumps({"engine": "postgresql", "version": info["version"], "database": info["db"]}), flush=True)

        def new_ctx(profile):
            ctx = launch(pw, profile)
            ctx.on("request", lambda r: seen.append(r.url))
            return ctx

        def open_lab(ctx, offline=False, wait=True):
            ctx.set_offline(offline)
            page = ctx.new_page()
            page.set_default_timeout(60000)
            assert page.goto(LAB, wait_until="domcontentloaded", timeout=60000).status == 200
            if wait:
                page.locator("#e2e-auth-status").get_by_text("Sesión en línea", exact=False).or_(page.locator("#e2e-auth-status").get_by_text("Sin sesión", exact=False)).or_(
                    page.locator("#e2e-auth-status").get_by_text("Sin conexión", exact=False)).first.wait_for()
            return page

        def wait_say(page, text, timeout=30000):
            """Wait for a status line; on failure show what the page actually said (diagnostics for CI logs)."""
            try:
                page.locator("#e2e-status").get_by_text(text, exact=False).first.wait_for(timeout=timeout)
            except Exception:
                print("STATUS WAS:", page.locator("#e2e-status").inner_text(), "| AUTH:", page.locator("#e2e-auth-status").inner_text(), flush=True)
                raise

        def login(page, user, password=None):
            page.locator("#e2e-login-user").fill(user["username"])
            page.locator("#e2e-login-pass").fill(password or user["password"])
            page.locator("#e2e-login-submit").click()

        def auth_state(page):
            return page.locator("#e2e-auth-status").get_attribute("data-state")

        def wait_auth(page, state):
            page.wait_for_function("(s) => document.querySelector('#e2e-auth-status')?.dataset.state === s", arg=state)

        def logout(page):
            page.locator("#e2e-logout").click()
            wait_auth(page, "anonymous")

        def prepare(page, secret=SECRET, machine="MP1"):
            page.locator("#e2e-prepare-machine").fill(machine)
            page.locator("#e2e-prepare-pass").fill(secret)
            page.locator("#e2e-prepare-submit").click()

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
            try:
                page.wait_for_function("([id, st]) => document.querySelector(`#e2e-captures li[data-draft-id='${id}']`)?.dataset.stage === st", arg=[draft_id, expected], timeout=30000)
            except Exception:
                print("STAGE WANTED", expected, "| LI:", page.locator(f"#e2e-captures li[data-draft-id='{draft_id}']").inner_text(), "| RESULT:", page.locator("#e2e-result").inner_text(),
                      "| STATUS:", page.locator("#e2e-status").inner_text(), flush=True)
                raise

        def capture_id(page, draft_id):
            li = page.locator(f"#e2e-captures li[data-draft-id='{draft_id}']")
            return li.get_attribute("data-capture-id")

        def sync(page, expect=None):
            page.locator("#e2e-sync-now").click()
            status = page.locator("#e2e-status")
            if expect:
                status.get_by_text(expect, exact=False).first.wait_for()
            else:
                status.get_by_text("finalizada", exact=False).or_(status.get_by_text("pausada", exact=False)).or_(status.get_by_text("Sin conexión", exact=False)).or_(
                    status.get_by_text("se interrumpió", exact=False)).first.wait_for()

        def receipts_for(ids):
            return [r for r in srv.receipts() if r["capture_id"] in ids]

        # ---- 01 login (UI): wrong credentials, then correct; the cookie is real, QA-exclusive, HttpOnly, Secure, SameSite=Lax ----
        main_profile = Path(tmp) / "main"
        ctx = new_ctx(main_profile)
        page = open_lab(ctx)
        assert auth_state(page) == "anonymous" and not [c for c in ctx.cookies() if c["name"] in (COOKIE, "vinto_session")]
        login(page, A, "wrong-password-0000")
        wait_say(page, "Credenciales incorrectas.")
        assert auth_state(page) == "anonymous" and not ctx.cookies()
        login(page, {"username": "nobody.exists", "password": "whatever-123456"})
        wait_say(page, "Credenciales incorrectas.")          # same message: no account oracle
        login(page, A)
        wait_auth(page, "ok")
        assert A["username"] in page.locator("#e2e-auth-status").inner_text()
        cookies = [c for c in ctx.cookies() if c["name"] == COOKIE]
        assert len(cookies) == 1 and cookies[0]["httpOnly"] is True and cookies[0]["secure"] is True and cookies[0]["sameSite"] == "Lax", ctx.cookies()
        assert not [c for c in ctx.cookies() if c["name"] == "vinto_session"]
        assert COOKIE not in page.evaluate("() => document.cookie")                                          # JS can never read it
        report("01_login_wrong_credentials_and_real_cookie_httponly_secure_samesite")

        # ---- 02 tampered signatures are refused by the device (separate throwaway profile) ----
        tctx = new_ctx(Path(tmp) / "tamper")
        tp = open_lab(tctx)
        login(tp, A); wait_auth(tp, "ok")
        srv.get("/__test__/tamper?target=scope")
        prepare(tp)
        wait_say(tp, "No se pudo preparar el dispositivo")
        unlock(tp)
        wait_say(tp, "No hay alcance firmado local.")          # nothing unverified was stored
        srv.get("/__test__/tamper?target=package")
        prepare(tp)
        wait_say(tp, "No se pudo preparar el dispositivo")
        unlock(tp)
        wait_say(tp, "No hay definiciones sintéticas editables.")
        assert tp.locator("#e2e-new").is_disabled()
        tctx.close()
        report("02_altered_scope_and_package_signatures_are_rejected_nothing_unverified_is_stored")

        # ---- 03 online preparation with the real issuer: signed scope and synthetic P1-22 package; unlock ----
        prepare(page, "short")
        wait_say(page, "Frase local débil")
        prepare(page)
        wait_say(page, "Dispositivo preparado")
        unlock(page, "frase incorrecta 123456789!!")
        wait_say(page, "No fue posible desbloquear")
        unlock(page)
        wait_say(page, "Laboratorio desbloqueado (perfil original)")
        assert "SINTÉTICO" in page.locator("#e2e-package").inner_text() and "VINTO-P1-22" in page.locator("#e2e-package").inner_text()
        page.locator("#e2e-new").click(); page.locator("#f-numero_de_cuba").wait_for()
        keys = page.evaluate("() => Array.from(document.querySelectorAll('#e2e-fields [data-key]')).map(e => e.dataset.key)")
        assert keys == ["numero_de_cuba", "masa_humeda", "grado_de_refinacion_sr", "amperaje", "observacion"], keys        # the published P1-22 contract
        page.reload()
        page.locator("#e2e-auth-status").get_by_text("Sesión en línea", exact=False).wait_for()
        page.wait_for_function("async () => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller", timeout=60000)
        page.wait_for_function("async () => (await caches.open('vinto-off045lab-v1').then(c => c.keys())).length === 2", timeout=60000)
        page.close()
        report("03_synthetic_p1_22_scope_and_package_signed_verified_and_stored_encrypted")

        # ---- 04 OFFLINE: open from the service worker, capture, validate, incomplete draft, pending, bridge; nothing is sent ----
        page = open_lab(ctx, offline=True)
        assert auth_state(page) == "unreachable"
        assert "NO es aprobación industrial" in page.locator(".lab").inner_text() and "DATOS SINTÉTICOS" in page.locator(".lab").inner_text()
        page.get_by_text("Perfil local encontrado.", exact=False).wait_for()
        unlock(page)
        wait_say(page, "Laboratorio desbloqueado (perfil original)")
        a = new_capture(page, "C-A-SINT")
        assert stage(page, a) == "queued"
        page.locator("#e2e-new").click(); page.locator("#f-numero_de_cuba").wait_for()
        fill(page, "numero_de_cuba", "C-B-INCOMPLETA"); fill(page, "masa_humeda", "abc")
        page.locator("#e2e-save").click()
        page.get_by_text("NO se guardó: corrija los campos marcados.", exact=False).wait_for()
        fill(page, "masa_humeda", "10")
        page.locator("#e2e-save").click()
        page.get_by_text("incompleto, faltan 2 obligatorio(s)", exact=False).wait_for()
        b = page.locator("#e2e-editor").get_attribute("data-draft-id")
        page.locator("#e2e-queue").click()
        page.get_by_text("faltan campos obligatorios", exact=False).wait_for()
        assert stage(page, b) == "draft" and srv.receipts() == []
        sync(page, "Sin conexión")                                                                           # offline: nothing is sent and nothing changes
        assert stage(page, a) == "queued" and srv.receipts() == []
        report("04_offline_capture_validation_incomplete_draft_pending_bridge_and_no_send_without_connection")

        # ---- 05 close the browser, reopen OFFLINE, unlock the original profile, recover everything ----
        ctx.close()
        ctx = new_ctx(main_profile)
        page = open_lab(ctx, offline=True)
        unlock(page)
        wait_say(page, "Laboratorio desbloqueado (perfil original)")
        assert stage(page, a) == "queued" and stage(page, b) == "draft"
        page.locator(f"#e2e-captures li[data-draft-id='{a}'] button.open").click()
        page.get_by_text("CONTENIDO CONGELADO", exact=False).first.wait_for()
        assert page.locator("#f-numero_de_cuba").input_value() == "C-A-SINT" and page.locator("#f-masa_humeda").input_value() == "12.5" and page.locator("#f-numero_de_cuba").is_disabled()
        report("05_restart_without_internet_unlock_original_profile_and_recover_pendings")

        # ---- 06 reconnect: the real session survives the restart; sync once; ONE record in PostgreSQL ----
        ctx.set_offline(False)
        page.reload()
        unlock(page)
        wait_say(page, "Laboratorio desbloqueado (perfil original)")
        page.locator("#e2e-auth-status").get_by_text("Sesión en línea", exact=False).wait_for()
        sync(page)
        wait_stage(page, a, "synced")
        cid = capture_id(page, a)
        rec = receipts_for({cid})
        assert len(rec) == 1 and rec[0]["outcome"] == "accepted" and rec[0]["author"] == A["id"], rec
        li = page.locator(f"#e2e-captures li[data-draft-id='{a}']").inner_text()
        assert "NO es aprobación industrial" in li and "servidor srv-" in li
        device = page.evaluate("() => localStorage.getItem('vinto-device-key')")
        assert device and cid == expected_capture_id(A["id"], device, a)
        assert srv.deliveries(cid) == 1
        report("06_reconnect_sync_with_the_real_session_and_single_confirmation_in_postgres")

        # ---- 07 response lost after persistence; reconciled without a duplicate ----
        c = new_capture(page, "C-C-SINT")
        srv.get("/__test__/lose?n=1")
        sync(page)
        wait_stage(page, c, "retry_wait")
        cid_c = capture_id(page, c)
        assert len(receipts_for({cid_c})) == 1 and srv.deliveries(cid_c) == 1, "the server persisted it although the response was lost"
        assert "incierto" in page.locator(f"#e2e-captures li[data-draft-id='{c}']").inner_text()
        page.locator("#e2e-clock").click()
        sync(page)
        wait_stage(page, c, "synced")
        assert len(receipts_for({cid_c})) == 1 and srv.deliveries(cid_c) == 1, "reconciled by GET: no second POST"
        report("07_lost_response_after_persistence_reconciled_without_duplicate")

        # ---- 08 network interruption keeps the pending and sends nothing ----
        d = new_capture(page, "C-D-SINT")
        ctx.route("**/api/offline/captures", lambda route: route.abort("connectionfailed") if route.request.method == "POST" else route.continue_())
        sync(page)
        wait_stage(page, d, "retry_wait")
        assert receipts_for({capture_id(page, d)}) == []
        ctx.unroute("**/api/offline/captures")
        page.locator("#e2e-clock").click()
        sync(page)
        wait_stage(page, d, "synced")
        assert len(receipts_for({capture_id(page, d)})) == 1
        report("08_network_interruption_keeps_the_pending_then_syncs_once")

        # ---- 09 other authenticated user, no session, revoked and expired sessions pause everything; the original author syncs ----
        e = new_capture(page, "C-E-SINT")
        before = len(srv.receipts())
        logout(page); login(page, B); wait_auth(page, "ok")
        sync(page)
        page.get_by_text("sesión en línea es de otro usuario", exact=False).first.wait_for()
        assert stage(page, e) == "queued" and len(srv.receipts()) == before
        logout(page)
        sync(page)
        page.get_by_text("No hay sesión en línea válida", exact=False).first.wait_for()
        assert stage(page, e) == "queued" and len(srv.receipts()) == before
        for action in ("revoke", "expire"):
            login(page, A); wait_auth(page, "ok")
            srv.get(f"/__test__/session?action={action}&user=a")
            sync(page)
            page.get_by_text("No hay sesión en línea válida", exact=False).first.wait_for()
            assert stage(page, e) == "queued" and len(srv.receipts()) == before, action
            wait_auth(page, "anonymous")                                                                       # the page noticed the dead session
        login(page, A); wait_auth(page, "ok")
        sync(page)
        wait_stage(page, e, "synced")
        assert len(srv.receipts()) == before + 1
        report("09_other_user_no_session_revoked_and_expired_sessions_pause_then_original_author_syncs")

        # ---- 10 a capture whose snapshot is not the one the pilot grant names (readiness-only) is refused by the server ----
        srv.get("/__test__/repin")
        f = new_capture(page, "C-F-SINT")
        before = len(srv.receipts())
        sync(page)
        page.wait_for_function("(id) => ['requires_review', 'conflict', 'retry_wait'].includes(document.querySelector(`#e2e-captures li[data-draft-id='${id}']`)?.dataset.stage)", arg=f)
        assert len(srv.receipts()) == before and receipts_for({capture_id(page, f)}) == [], "a read-only snapshot never authorises a capture"
        f_stage = stage(page, f)
        srv.get("/__test__/repin?snapshot=" + SNAPSHOT)
        report("10_readiness_only_snapshot_rejected_by_the_server_nothing_persisted")

        # ---- 11 two simultaneous tabs: one logical capture, one POST ----
        tab2 = open_lab(ctx)
        unlock(tab2)
        wait_say(tab2, "Laboratorio desbloqueado (perfil original)")
        i = new_capture(page, "C-I-SINT")
        tab2.reload(); unlock(tab2)
        wait_say(tab2, "Laboratorio desbloqueado (perfil original)")
        assert stage(tab2, i) == "queued"
        iid = capture_id(page, i)
        page.locator("#e2e-sync-now").click(no_wait_after=True)
        tab2.locator("#e2e-sync-now").click(no_wait_after=True)
        wait_stage(page, i, "synced")
        tab2.reload(); unlock(tab2)
        wait_stage(tab2, i, "synced")
        # Keep strict single-POST invariant; print only event metadata when broken.
        if srv.deliveries(iid) != 1:
            events = [{"kind": e.get("kind"), "capture_id": e.get("capture_id"), "at": e.get("at")}
                      for e in srv.get("/__test__/events") if e.get("capture_id") == iid]
            print("OFF06B_MULTITAB_EVENT_DIAG=" + json.dumps(events), flush=True)
        assert len(receipts_for({iid})) == 1 and srv.deliveries(iid) == 1, (srv.deliveries(iid), receipts_for({iid}))
        tab2.close()
        report("11_two_simultaneous_tabs_send_once_and_register_once")

        # ---- 12 storage failure during synchronisation keeps every pending, recovers afterwards ----
        j = new_capture(page, "C-J-SINT")
        before = len(srv.receipts())
        page.evaluate("""() => { const orig = IDBObjectStore.prototype.put; window.__origPut = orig;
            IDBObjectStore.prototype.put = function (...a) { IDBObjectStore.prototype.put = orig; throw new DOMException('injected', 'QuotaExceededError'); }; }""")
        sync(page)
        page.get_by_text("error de almacenamiento", exact=False).first.wait_for()
        page.evaluate("() => { if (window.__origPut) IDBObjectStore.prototype.put = window.__origPut; }")
        page.locator(f"#e2e-captures li[data-draft-id='{j}']").wait_for()
        assert stage(page, j) in ("queued", "syncing") and len(srv.receipts()) == before
        sync(page)
        wait_stage(page, j, "synced")
        assert len(srv.receipts()) == before + 1
        report("12_storage_failure_keeps_pendings_and_recovers")

        # ---- 13 unauthorised writes with the REAL cookie are blocked: guard, Origin allow-list, unmounted industrial routes ----
        cookie = "; ".join(f"{c['name']}={c['value']}" for c in ctx.cookies() if c["name"] == COOKIE)
        assert cookie
        n0 = len(srv.receipts())
        good = {"Cookie": cookie, "Origin": origin, "Content-Type": "application/json"}
        body = {"capture_id": "00000000-0000-4000-8000-000000000001"}
        for method, path, hdrs in (("POST", "/api/captures", good), ("POST", "/api/bobbins", good), ("POST", "/api/admin/users", good), ("POST", "/api/quality/machines/MP1/captures", good),
                                   ("PUT", "/api/work-orders/1", good), ("DELETE", "/api/offline/captures", good), ("POST", "/api/offline/sync", good)):
            assert srv.request(method, path, headers=hdrs, body=body)[0] == 403, (method, path)                  # the QA guard
        for origin_header in (None, "https://evil.example", "null", origin + "/", origin.replace("127.0.0.1", "localhost")):
            hdrs = {"Cookie": cookie, "Content-Type": "application/json", **({"Origin": origin_header} if origin_header else {})}
            assert srv.request("POST", "/api/offline/captures", headers=hdrs, body=body)[0] == 403, origin_header  # CSRF: the Origin must be the allowed one
            assert srv.request("POST", "/api/auth/logout", headers=hdrs)[0] == 403, origin_header
        for path in ("/api/captures", "/api/work-orders", "/api/admin/users", "/api/quality/machines/MP1", "/openapi.json", "/docs"):
            assert srv.request("GET", path, headers={"Cookie": cookie})[0] == 404, path                           # industrial routes are not mounted
        assert srv.request("GET", "/api/auth/me", headers={"Cookie": cookie})[0] == 200                          # and the session survived all of the above
        assert len(srv.receipts()) == n0
        report("13_unauthorised_writes_with_a_real_cookie_are_blocked_and_industrial_routes_do_not_exist")

        # ---- 14 final accounting: one logical capture each, the incomplete draft kept, only the same origin was contacted ----
        ids = [capture_id(page, x) for x in (a, c, d, e, i, j)]
        server_ids = [r["capture_id"] for r in srv.receipts()]
        assert sorted(server_ids) == sorted(ids) and len(set(server_ids)) == len(server_ids), (server_ids, ids)
        assert all(srv.deliveries(x) == 1 for x in ids), [(x, srv.deliveries(x)) for x in ids]
        assert all(r["author"] == A["id"] for r in srv.receipts())
        assert stage(page, b) == "draft" and f_stage in ("requires_review", "conflict", "retry_wait") and stage(page, f) == f_stage
        stray = [u for u in seen if not (u.startswith(origin) or u.startswith(("data:", "about:", "blob:")))]
        assert stray == [], stray
        assert not [u for u in seen if "X-Synthetic" in u or "receiver=" in u]
        ctx.close()
        report("14_one_logical_capture_each_same_origin_only_and_nothing_lost")
    finally:
        srv.stop()

# ---- 15 flags OFF (the default of the real entrypoint): no login, no capture, guard intact ----
with tempfile.TemporaryDirectory(prefix="vinto-off06b-off-") as tmp, sync_playwright() as pw:
    off = Server("off")
    try:
        user = {"username": "nobody", "password": "whatever-123456"}
        h = {"Origin": off.origin, "Content-Type": "application/json"}
        assert off.request("POST", "/api/offline/captures", headers=h, body={})[0] == 403
        assert off.request("POST", "/api/captures", headers=h, body={})[0] == 403
        assert off.request("POST", "/api/auth/login", headers=h, body=user)[0] in (404, 405)                     # allowed by the QA guard, but no such route is mounted (405: this disposable server's static mount)
        for path in ("/api/auth/me", "/api/offline/scope", "/api/offline/captures/00000000-0000-4000-8000-000000000001"):
            assert off.request("GET", path)[0] == 404, path
        assert off.get("/__test__/info")["receipts"] == 0
        ctx = launch(pw, Path(tmp) / "p")
        page = ctx.new_page(); page.set_default_timeout(60000)
        assert page.goto(off.origin + "/offline-e2e-lab.html", wait_until="domcontentloaded").status == 200
        page.locator("#e2e-auth-status").get_by_text("Sin conexión con el servidor QA.", exact=False).wait_for()   # no session service: the page degrades, nothing is created
        page.locator("#e2e-login-user").fill("nobody"); page.locator("#e2e-login-pass").fill("whatever-123456"); page.locator("#e2e-login-submit").click()
        wait_say(page, "No se pudo iniciar sesión ahora.")
        assert [c for c in ctx.cookies()] == []
        ctx.close()
        report("15_flags_off_by_default_no_login_no_capture_and_guard_intact")
    finally:
        off.stop()
print("OFF04_5B_06B_MOBILE_AUTH_E2E=PASS", flush=True)
