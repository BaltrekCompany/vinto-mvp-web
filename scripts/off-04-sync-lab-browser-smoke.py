#!/usr/bin/env python3
"""OFF-04.3 real Chrome through the SYNC LABORATORY page (fake in-memory server, synthetic data).

Requires a build made with OFFLINE_DRAFT_LAB=1. After the local profile is prepared, any /api/ request is recorded and must
not exist: the engine talks only to the in-page fake server.
"""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from off03b3_fixture import USER_ID

BASE = os.environ["OFF04_BASE_URL"]
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
SECRET = "VINTO OFF043 lab browser synthetic secret 5531!!"


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


def launch(pw, profile):
    kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], service_workers="allow", **kwargs)


with tempfile.TemporaryDirectory(prefix="vinto-off043-ui-") as tmp, sync_playwright() as pw:
    profile = Path(tmp) / "browser"
    origin = BASE.rstrip("/")
    cors = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    api_calls = []

    def install(page):
        def mock(route):
            api_calls.append(route.request.method + " " + route.request.url.split("/api/")[-1])
            if route.request.method == "OPTIONS":
                route.fulfill(status=204, headers=cors)
                return
            data = {"user": {"id": USER_ID, "username": "synthetic.quality", "display_name": "Synthetic Quality",
                             "profiles": ["CALIDAD"], "permissions": ["quality.capture"], "must_change": False}}
            route.fulfill(status=200, headers={"Content-Type": "application/json", "Cache-Control": "no-store", **cors}, body=json.dumps(data))
        page.route("**/api/auth/me", mock)

    def unlock(page, secret=SECRET, confirm=True):
        page.locator("#sync-unlock-secret").fill(secret)
        if confirm:
            page.locator("#sync-confirm").check()
        page.locator("#sync-unlock-submit").click()

    def states(page):
        return [li.get_attribute("data-state") for li in page.locator("#sync-list li[data-state]").all()]

    def sync(page, expect=None):
        page.locator("#sync-now").click()
        if expect:
            page.get_by_text(expect, exact=False).first.wait_for()

    ctx = launch(pw, profile)
    page = ctx.new_page()
    page.set_default_timeout(90000)
    install(page)
    page.goto(BASE + "/offline-preparacion", wait_until="domcontentloaded", timeout=120000)
    page.get_by_text("Preparación de prueba: crea una clave local protegida", exact=False).wait_for()
    page.locator('input[type="password"]').nth(0).fill(SECRET)
    page.locator('input[type="password"]').nth(1).fill(SECRET)
    page.get_by_role("button", name="Preparar perfil local").click()
    page.get_by_text("Perfil preparado", exact=False).wait_for()
    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller", timeout=60000)
    report("01_profile_prepared_online")

    api_calls.clear()
    lab = ctx.new_page()
    lab.set_default_timeout(90000)
    install(lab)
    assert lab.goto(BASE + "/offline-sync-lab.html", wait_until="domcontentloaded").status == 200
    lab.get_by_text("Perfil local encontrado.", exact=False).wait_for()
    assert "SERVIDOR SIMULADO" in lab.locator(".lab").inner_text() and "NO se conecta con FastAPI" in lab.locator(".lab").inner_text()
    lab.wait_for_function("async () => (await caches.open('vinto-off043lab-v1').then(c => c.keys())).length === 2", timeout=60000)
    unlock(lab, confirm=False)
    lab.get_by_text("Confirme que usará únicamente datos sintéticos", exact=False).wait_for()
    unlock(lab, "frase incorrecta 123456789!!")
    lab.get_by_text("No fue posible desbloquear.", exact=False).wait_for()
    assert lab.locator("#sync-workspace").is_hidden()
    unlock(lab)
    lab.get_by_text("Laboratorio de sincronización desbloqueado.", exact=False).wait_for()
    report("02_lab_page_marked_simulated_requires_unlock")

    # ---- success, with a dependent record, double click on "Sincronizar ahora" ----
    lab.locator("#sync-add").click(); lab.get_by_text("Captura de prueba creada", exact=False).wait_for()
    lab.locator("#sync-depends").check()
    lab.locator("#sync-add").click(); lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state]').length === 2")
    lab.locator("#sync-depends").uncheck()
    assert states(lab) == ["queued", "queued"]
    lab.locator("#sync-now").dblclick()
    lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state=synced]').length === 2")
    assert "2 captura(s) lógica(s) registrada(s) en 2 envío(s)" in lab.locator("#sync-server").inner_text()
    assert "synced=2" in lab.locator("#sync-counters").inner_text()
    report("03_success_with_dependency_and_double_click")

    # ---- response lost after the server persisted: reconcile, never a second registration ----
    lab.locator("#sync-add").click(); lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state]').length === 3")
    lab.locator("#sync-fault").select_option("lose_response"); lab.locator("#sync-arm").click()
    sync(lab, "Se detuvo por: network")
    assert states(lab)[-1] == "retry_wait" and "incierto" in lab.locator("#sync-list li").last.inner_text()
    sync(lab, "en espera 1")
    lab.locator("#sync-clock").click()
    lab.locator("#sync-now").click()
    lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state=synced]').length === 3")
    assert "3 captura(s) lógica(s) registrada(s) en 3 envío(s)" in lab.locator("#sync-server").inner_text(), lab.locator("#sync-server").inner_text()
    report("04_lost_response_is_reconciled_without_duplicate")

    # ---- session problems pause without changing anything ----
    lab.locator("#sync-add").click(); lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state]').length === 4")
    lab.locator("#sync-session").select_option("expired"); sync(lab, "No hay sesión en línea válida")
    assert states(lab)[-1] == "queued"
    lab.locator("#sync-session").select_option("other"); sync(lab, "sesión en línea es de otro usuario")
    assert states(lab)[-1] == "queued" and "3 captura(s)" in lab.locator("#sync-server").inner_text()
    lab.locator("#sync-session").select_option("valid")
    lab.locator("#sync-fault").select_option("s401"); lab.locator("#sync-arm").click()
    sync(lab, "La sesión en línea no es válida")
    assert states(lab)[-1] == "queued"
    sync(lab)
    lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state=synced]').length === 4")
    report("05_invalid_session_other_user_and_401_pause_then_resume")

    # ---- 403 => review, changed context => conflict; neither is retried automatically ----
    lab.locator("#sync-add").click(); lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state]').length === 5")
    lab.locator("#sync-fault").select_option("s403"); lab.locator("#sync-arm").click()
    sync(lab); lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state=requires_review]').length === 1")
    lab.locator("#sync-add").click(); lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state]').length === 6")
    lab.locator("#sync-context").check(); sync(lab)
    lab.wait_for_function("() => document.querySelectorAll('#sync-list li[data-state=conflict]').length === 1")
    assert "context_changed" in lab.locator("#sync-list li[data-state=conflict]").inner_text()
    before = lab.locator("#sync-server").inner_text()
    sync(lab); lab.get_by_text("enviadas 0", exact=False).wait_for()
    assert lab.locator("#sync-server").inner_text() == before
    report("06_forbidden_review_and_changed_context_conflict_are_not_retried")
    assert [c for c in api_calls if not c.startswith("OPTIONS")] == [], api_calls
    ctx.close()

    # ---- restart OFFLINE: the lab page comes from the service worker; persisted states survive ----
    ctx = launch(pw, profile)
    ctx.set_offline(True)
    off = ctx.new_page()
    off.set_default_timeout(90000)
    assert off.goto(BASE + "/offline-sync-lab.html", wait_until="domcontentloaded", timeout=60000).status == 200
    off.get_by_text("Perfil local encontrado.", exact=False).wait_for()
    unlock(off)
    off.get_by_text("Laboratorio de sincronización desbloqueado.", exact=False).wait_for()
    assert states(off) == ["synced", "synced", "synced", "synced", "requires_review", "conflict"], states(off)
    assert "synced=4" in off.locator("#sync-counters").inner_text() and "conflict=1" in off.locator("#sync-counters").inner_text()
    assert [c for c in api_calls if not c.startswith("OPTIONS")] == [], api_calls
    report("07_states_persist_after_restart_and_page_works_offline")
    ctx.close()
print("OFF04_3_SYNC_LAB_UI=PASS", flush=True)
