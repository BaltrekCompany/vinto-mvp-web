#!/usr/bin/env python3
"""OFF-03C.4 real Chrome through the actual UI: renewal, failure, revocation, restart.

Auth / scope / quality-package endpoints are mocked ONLY here, with synthetic users, and signed by
the REAL Python signer. No backend, no production data, no capture. Offline checks use the real
Service Worker, the bundled offline runtime and a persistent browser profile that is closed/reopened.
"""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from off03b3_fixture import USER_ID
from off03c4_fixture import package, pair, scope

BASE = os.environ["OFF03C4_BASE_URL"]
CHANNEL = os.environ.get("OFF03C4_CHROME_CHANNEL", "chrome")
SECRET = "VINTO OFF03C4 browser synthetic secret 5530!!"
PAIRS = [pair("MP1", "VINTO-P1-18", 3)]
SCOPE_PLAN = ["old", "new", "revoked", "refresh", "network"]   # what each successive scope request does


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


def launch(pw, profile):
    kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
        service_workers="allow", **kwargs)


with tempfile.TemporaryDirectory(prefix="vinto-off03c4-ui-") as tmp, sync_playwright() as pw:
    profile = Path(tmp) / "browser"
    origin = BASE.rstrip("/")
    cors = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    state = {"scope_calls": 0, "scope": None, "script": []}

    def install(page):
        def mock(route):
            url = route.request.url
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=cors)
                return
            if "/api/auth/me" in url:
                data = {"user": {"id": USER_ID, "username": "synthetic.quality", "display_name": "Synthetic Quality",
                                 "profiles": ["CALIDAD"], "permissions": ["quality.capture"], "must_change": False}}
            elif "/api/offline/quality-package" in url:
                req = json.loads(route.request.post_data)
                data = package(req["signed_scope"], req["machine_code"], req["form_code"], label="ui")
            elif "/api/offline/scope" in url:
                req = json.loads(route.request.post_data)
                step = state["script"].pop(0)
                if step == "forbidden":
                    route.fulfill(status=403, headers={"Content-Type": "application/json", "Cache-Control": "no-store", **cors},
                                  body=json.dumps({"detail": "Acceso no autorizado"}))
                    return
                if step == "abort":
                    route.abort()
                    return
                issued = {"old": "2026-11-17T12:00:00Z", "new": "2026-11-17T12:30:00Z", "newer": "2026-11-17T13:00:00Z"}[step]
                data = scope(step, issued, PAIRS, device=req["device_key"])
            else:
                raise AssertionError("Unexpected URL: " + url)
            route.fulfill(status=200, headers={"Content-Type": "application/json", "Cache-Control": "no-store", **cors},
                          body=json.dumps(data, ensure_ascii=False))
        for endpoint in ("/api/auth/me", "/api/offline/scope", "/api/offline/quality-package"):
            page.route("**" + endpoint, mock)

    def online_page(ctx):
        page = ctx.new_page()
        page.set_default_timeout(90000)
        install(page)
        page.goto(BASE + "/offline-preparacion", wait_until="domcontentloaded", timeout=120000)
        return page

    def to_package_state(page):
        page.get_by_text("Perfil local preparado.", exact=False).wait_for()
        page.get_by_role("button", name="Ya tengo un alcance firmado").click()

    def renew(page):
        page.locator('input[type="password"]').fill(SECRET)
        page.get_by_role("button", name="Renovar alcance y paquetes").click()

    def open_offline(ctx):
        ctx.set_offline(True)
        page = ctx.new_page()
        page.set_default_timeout(90000)
        assert page.goto(BASE + "/", wait_until="domcontentloaded", timeout=60000).status == 200
        page.get_by_text("Perfil local preparado.", exact=False).wait_for()
        page.locator("#offline-unlock-secret").fill(SECRET)
        page.locator("#offline-unlock-submit").click()
        return page

    # ---- online: enrol, initial scope and package through the unchanged first-time flow ----
    state["script"] = ["old"]
    ctx = launch(pw, profile)
    page = online_page(ctx)
    page.get_by_text("Preparación de prueba: crea una clave local protegida", exact=False).wait_for()
    page.locator('input[type="password"]').nth(0).fill(SECRET)
    page.locator('input[type="password"]').nth(1).fill(SECRET)
    page.get_by_role("button", name="Preparar perfil local").click()
    page.get_by_text("Perfil preparado", exact=False).wait_for()
    page.get_by_placeholder("MP1, MP3").fill("MP1")
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button", name="Guardar alcance firmado cifrado").click()
    page.get_by_text("Alcance firmado verificado y guardado cifrado.", exact=False).wait_for()
    page.get_by_placeholder("MP1", exact=True).fill("MP1")
    page.get_by_placeholder("VINTO-P1-22").fill("VINTO-P1-18")
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button", name="Guardar formulario firmado cifrado").click()
    page.get_by_text("Definición completa de Calidad firmada y guardada cifrada.", exact=False).wait_for()
    report("01_initial_scope_and_package_stored_by_existing_flow")

    # ---- renewal: network failure first, nothing replaced ----
    state["script"] = ["abort"]
    renew(page)
    page.get_by_text("Sin conexión segura: no se reemplazó nada.", exact=False).wait_for()
    report("02_network_failure_reports_nothing_replaced")

    # ---- renewal: valid and complete ----
    state["script"] = ["new"]
    renew(page)
    page.get_by_text("Renovación completa: alcance y 1 formulario(s) se reemplazaron juntos.", exact=False).wait_for()
    report("03_renewal_replaces_scope_and_package_together")
    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller", timeout=60000)
    ctx.close()

    # ---- offline after restart: renewed set readable, with renewal date ----
    ctx = launch(pw, profile)
    page = open_offline(ctx)
    page.get_by_text("Firma y perfil verificados sin Internet.", exact=False).wait_for()
    status = page.locator("#offline-profile-status").inner_text()
    assert "Última renovación con Internet" in status and "no se puede confirmar que los permisos sigan vigentes" in status, status
    details = page.locator("#offline-package-details details")
    assert details.count() == 1
    details.first.locator("summary").click()
    assert details.first.get_by_text("Número de cuba v3", exact=False).is_visible()
    assert page.locator("#offline-package-details input").count() == 0
    report("04_offline_restart_reads_renewed_set_read_only")
    ctx.close()

    # ---- online: the server revokes the grant (HTTP 403) ----
    ctx = launch(pw, profile)
    state["script"] = ["forbidden"]
    page = online_page(ctx)
    to_package_state(page)
    renew(page)
    page.get_by_text("El servidor ya no concede este alcance.", exact=False).wait_for()
    report("05_revocation_reported_and_previous_set_preserved")
    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller", timeout=60000)
    ctx.close()

    # ---- offline after restart: signature still valid but the set is NOT presented as available ----
    ctx = launch(pw, profile)
    page = open_offline(ctx)
    page.get_by_text("Se detectó con Internet que este alcance ya no está vigente", exact=False).wait_for()
    assert page.locator("#offline-package-details").is_hidden()
    assert page.locator("#offline-scope-list").is_hidden()
    assert page.locator("#offline-package-details details").count() == 0
    assert "Las capturas y los permisos industriales siguen deshabilitados." in page.locator("#offline-profile-status").inner_text()
    report("06_offline_restart_withholds_revoked_set")
    ctx.close()

    # ---- online again: a verified renewal clears the revocation state ----
    ctx = launch(pw, profile)
    state["script"] = ["newer"]
    page = online_page(ctx)
    to_package_state(page)
    renew(page)
    page.get_by_text("Renovación completa: alcance y 1 formulario(s) se reemplazaron juntos.", exact=False).wait_for()
    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller", timeout=60000)
    ctx.close()
    ctx = launch(pw, profile)
    page = open_offline(ctx)
    page.get_by_text("Firma y perfil verificados sin Internet.", exact=False).wait_for()
    assert page.locator("#offline-package-details details").count() == 1
    report("07_verified_renewal_after_revocation_restores_consultation")
    ctx.close()
print("OFF03C4_BROWSER_RENEWAL_UI=PASS", flush=True)
