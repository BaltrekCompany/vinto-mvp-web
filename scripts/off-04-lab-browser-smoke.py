#!/usr/bin/env python3
"""OFF-04.1 real Chrome through the LABORATORY page: create/edit drafts, close, reopen OFFLINE, recover.

Auth / scope / package endpoints are mocked here only, with synthetic users and the real Python signer.
Requires a build made with OFFLINE_DRAFT_LAB=1. No central write call is allowed: every /api/ request
after the preparation phase is recorded and must not exist.
"""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from off03b3_fixture import USER_ID
from off03c4_fixture import pair, scope
from off04_fixture import FORM, lab_package

BASE = os.environ["OFF04_BASE_URL"]
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
SECRET = "VINTO OFF04 lab browser synthetic secret 6619!!"
MARKER = "C-777-SINT"


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


def launch(pw, profile):
    kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
    return pw.chromium.launch_persistent_context(
        user_data_dir=str(profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"],
        service_workers="allow", **kwargs)


with tempfile.TemporaryDirectory(prefix="vinto-off04-ui-") as tmp, sync_playwright() as pw:
    profile = Path(tmp) / "browser"
    origin = BASE.rstrip("/")
    cors = {"Access-Control-Allow-Origin": origin, "Access-Control-Allow-Credentials": "true",
            "Access-Control-Allow-Methods": "GET,POST,OPTIONS", "Access-Control-Allow-Headers": "Content-Type"}
    api_calls = []

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
                req = json.loads(route.request.post_data)
                data = lab_package(req["signed_scope"], 1)
            elif "/api/offline/scope" in url:
                req = json.loads(route.request.post_data)
                data = scope("off04-ui", "2026-11-18T12:00:00Z", [pair("MP1", FORM, 1)], device=req["device_key"])
            else:
                raise AssertionError("Unexpected URL: " + url)
            route.fulfill(status=200, headers={"Content-Type": "application/json", "Cache-Control": "no-store", **cors},
                          body=json.dumps(data, ensure_ascii=False))
        for endpoint in ("/api/auth/me", "/api/offline/scope", "/api/offline/quality-package"):
            page.route("**" + endpoint, mock)

    def unlock(page, secret=SECRET, confirm=True):
        page.locator("#lab-unlock-secret").fill(secret)
        if confirm:
            page.locator("#lab-confirm-synthetic").check()
        page.locator("#lab-unlock-submit").click()

    def fill(page, key, value):
        el = page.locator("#f-" + key)
        if el.evaluate("e => e.tagName") == "SELECT":
            el.select_option(value)
        else:
            el.fill(value)

    # ---- online preparation through the existing UI: profile, signed scope, synthetic package ----
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
    page.get_by_placeholder("MP1, MP3").fill("MP1")
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button", name="Guardar alcance firmado cifrado").click()
    page.get_by_text("Alcance firmado verificado y guardado cifrado.", exact=False).wait_for()
    page.get_by_placeholder("MP1", exact=True).fill("MP1")
    page.get_by_placeholder("VINTO-P1-22").fill(FORM)
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button", name="Guardar formulario firmado cifrado").click()
    page.get_by_text("Definición completa de Calidad firmada y guardada cifrada.", exact=False).wait_for()
    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller", timeout=60000)
    report("01_online_preparation_of_profile_scope_and_synthetic_package")

    # ---- the lab page itself: no /api/ traffic at all from here on ----
    api_calls.clear()
    lab = ctx.new_page()
    lab.set_default_timeout(90000)
    install(lab)
    assert lab.goto(BASE + "/offline-lab.html", wait_until="domcontentloaded").status == 200
    lab.get_by_text("Perfil local encontrado.", exact=False).wait_for()
    assert "DATOS SINTÉTICOS" in lab.locator(".lab").inner_text()
    lab.wait_for_function("async () => (await caches.open('vinto-off04lab-v1').then(c => c.keys())).length === 2", timeout=60000)
    report("02_lab_page_served_marked_synthetic_and_self_caches")

    unlock(lab, confirm=False)
    lab.get_by_text("Confirme que usará únicamente datos sintéticos.", exact=False).wait_for()
    unlock(lab, "frase incorrecta 123456789!!")
    lab.get_by_text("No fue posible desbloquear o validar.", exact=False).wait_for()
    assert lab.locator("#lab-workspace").is_hidden() and lab.locator("#lab-editor").is_hidden()
    unlock(lab)
    lab.get_by_text("Laboratorio desbloqueado.", exact=False).wait_for()
    report("03_unlock_required_wrong_phrase_and_missing_confirmation_refused")

    lab.locator("#lab-new-draft").click()
    lab.locator("#f-numero_de_cuba").wait_for()
    calc = lab.locator("#f-consistencia_pct")
    assert calc.is_disabled() and calc.get_attribute("data-calculated") == "1"
    assert "calculado por backend" in lab.locator("#lab-fields").inner_text()
    assert lab.locator("button:has-text('Enviar'), button:has-text('Sincronizar'), button:has-text('Cola')").count() == 0
    fill(lab, "numero_de_cuba", MARKER)
    fill(lab, "masa_humeda_g", "abc")
    lab.locator("#lab-save").click()
    lab.get_by_text("NO se guardó: corrija los campos marcados.", exact=False).wait_for()
    assert lab.locator("#err-masa_humeda_g").inner_text() == "valor no válido para el tipo"
    fill(lab, "masa_humeda_g", "120,5")
    lab.locator("#lab-save").click()
    lab.get_by_text("Borrador guardado cifrado en este navegador (revisión 1).", exact=False).wait_for()
    assert "incompleto" in lab.locator("#lab-status").inner_text() and "No se envió nada" in lab.locator("#lab-status").inner_text()
    for key, value in (("tipo_pasta", "estandar"), ("masa_seca_g", "30"), ("cantidad_muestras", "2"),
                       ("fecha_muestreo", "2026-11-18"), ("muestra_valida", "true")):
        fill(lab, key, value)
    lab.locator("#lab-save").click()
    lab.get_by_text("(revisión 2)", exact=False).wait_for()
    assert "completo" in lab.locator("#lab-status").inner_text() and "incompleto" not in lab.locator("#lab-status").inner_text()
    assert lab.locator("#lab-drafts button.open").count() == 1
    report("04_create_edit_validate_and_save_encrypted_drafts")

    dump = lab.evaluate("""async () => await new Promise((resolve, reject) => {
        const r = indexedDB.open('vinto-off03a-profiles-v1'); r.onerror = () => reject(new Error('x'));
        r.onsuccess = () => { r.result.close();
          const q = indexedDB.open('vinto-offline-v1'); q.onerror = () => reject(new Error('y'));
          q.onsuccess = () => { const db = q.result; const g = db.transaction('drafts').objectStore('drafts').getAll();
            g.onsuccess = () => { const out = JSON.stringify(g.result); db.close(); resolve(out); }; }; }; })""")
    assert MARKER not in dump and "numero_de_cuba" not in dump and "Laboratorio de Calidad" not in dump
    assert json.loads(dump)[0]["sealed"]["format"] == "aes-gcm-v1" and len(json.loads(dump)) == 1
    ls = lab.evaluate("() => JSON.stringify(Object.entries(localStorage))")
    assert MARKER not in ls
    assert [c for c in api_calls if not c.startswith("OPTIONS")] == [], api_calls
    report("05_nothing_in_clear_in_indexeddb_or_localstorage_and_no_api_traffic")
    ctx.close()

    # ---- restart OFFLINE: lab page from the service worker, unlock, recover, edit ----
    ctx = launch(pw, profile)
    ctx.set_offline(True)
    off = ctx.new_page()
    off.set_default_timeout(90000)
    install(off)
    assert off.goto(BASE + "/offline-lab.html", wait_until="domcontentloaded", timeout=60000).status == 200
    off.get_by_text("Perfil local encontrado.", exact=False).wait_for()
    unlock(off, "otra frase incorrecta 9876543!!")
    off.get_by_text("No fue posible desbloquear o validar.", exact=False).wait_for()
    unlock(off)
    off.get_by_text("Laboratorio desbloqueado.", exact=False).wait_for()
    off.locator("#lab-drafts button.open").first.click()
    off.get_by_text("Borrador cargado (revisión 2).", exact=False).wait_for()
    assert off.locator("#f-numero_de_cuba").input_value() == MARKER
    assert off.locator("#f-masa_humeda_g").input_value() == "120.5"
    assert off.locator("#f-muestra_valida").input_value() == "true"
    assert off.locator("#f-consistencia_pct").is_disabled()
    fill(off, "observaciones", "editado sin conexión")
    off.locator("#lab-save").click()
    off.get_by_text("(revisión 3)", exact=False).wait_for()
    report("06_reopen_offline_after_restart_recover_and_edit_draft")

    # ---- a second tab saves first; this tab must not overwrite it ----
    tab2 = ctx.new_page()
    tab2.set_default_timeout(90000)
    tab2.goto(BASE + "/offline-lab.html", wait_until="domcontentloaded", timeout=60000)
    tab2.get_by_text("Perfil local encontrado.", exact=False).wait_for()
    unlock(tab2)
    tab2.get_by_text("Laboratorio desbloqueado.", exact=False).wait_for()
    tab2.locator("#lab-drafts button.open").first.click()
    tab2.get_by_text("Borrador cargado (revisión 3).", exact=False).wait_for()
    fill(tab2, "observaciones", "desde la segunda pestaña")
    tab2.locator("#lab-save").click()
    tab2.get_by_text("(revisión 4)", exact=False).wait_for()
    fill(off, "observaciones", "intento obsoleto")
    off.locator("#lab-save").click()
    off.get_by_text("NO se guardó: otra pestaña guardó una versión más reciente.", exact=False).wait_for()
    assert off.locator("#lab-reload").is_visible()
    off.locator("#lab-reload").click()
    off.get_by_text("Borrador cargado (revisión 4).", exact=False).wait_for()
    assert off.locator("#f-observaciones").input_value() == "desde la segunda pestaña"
    report("07_second_tab_wins_and_stale_tab_is_refused_without_overwrite")

    off.locator("#lab-lock").click()
    off.get_by_text("Laboratorio bloqueado.", exact=False).wait_for()
    assert off.locator("#lab-editor").is_hidden() and off.locator("#lab-workspace").is_hidden()
    assert [c for c in api_calls if not c.startswith("OPTIONS")] == [], api_calls
    report("08_lock_discards_key_and_no_central_write_call_was_made")
    ctx.close()
print("OFF04_LAB_UI=PASS", flush=True)
