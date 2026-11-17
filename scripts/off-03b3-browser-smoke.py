#!/usr/bin/env python3
"""OFF-03B.3 Chrome: signed scope mock from real backend signing module.

Online API responses are SYNTHETIC /api/auth/me and /api/offline/scope,
then a real Chrome profile is closed/reopened offline. No user/production data.
"""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from off03b3_fixture import USER_ID, sign_for_device

BASE=os.environ["OFF03B3_BASE_URL"]
SECRET="VINTO offline synthetic QA phrase 1199!#!"
def emit(name,**kwargs):
    print(json.dumps({"case":name,"result":"PASS",**kwargs},ensure_ascii=False),flush=True)
def open_ctx(browser,profile):
    return browser.launch_persistent_context(user_data_dir=str(profile),headless=True,channel="chrome",
         args=["--no-sandbox","--disable-dev-shm-usage"],service_workers="allow")
with tempfile.TemporaryDirectory(prefix="vinto-off03b3-") as tmp:
  path=Path(tmp)/"chrome-profile"
  with sync_playwright() as pw:
    ctx=open_ctx(pw.chromium,path)
    page=ctx.new_page()
    page.set_default_timeout(60000)
    def auth(route):
      route.fulfill(status=200,headers={"Content-Type":"application/json","Cache-Control":"no-store"},
         body=json.dumps({"user":{"id":USER_ID,"username":"qa.synthetic","display_name":"QA Synthetic",
             "profiles":["CALIDAD"],"permissions":["quality.capture"],"must_change":False}}))
    state={"rotated":False}
    def scope(route):
      req=json.loads(route.request.post_data)
      assert req["machine_codes"]==["MP1"],req
      body=sign_for_device(req["device_key"],rotated=state["rotated"])
      route.fulfill(status=200,headers={"Content-Type":"application/json","Cache-Control":"no-store"},
                    body=json.dumps(body,ensure_ascii=False))
    page.route("**/api/auth/me",auth)
    page.route("**/api/offline/scope",scope)
    page.goto(BASE+"/offline-preparacion",wait_until="domcontentloaded",timeout=120000)
    page.get_by_text("Preparación de prueba: crea una clave local protegida",exact=False).wait_for(timeout=60000)
    inputs=page.locator('input[type="password"]')
    inputs.nth(0).fill(SECRET)
    inputs.nth(1).fill(SECRET)
    page.get_by_role("button",name="Preparar perfil local").click()
    page.get_by_text("Perfil preparado",exact=False).wait_for(timeout=60000)
    emit("01_online_enrollment_mocked_session")

    page.get_by_placeholder("MP1, MP3").fill("MP1")
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button",name="Guardar alcance firmado cifrado").click()
    page.get_by_text("Alcance firmado verificado y guardado cifrado.",exact=False).wait_for(timeout=60000)
    emit("02_signed_python_scope_sealed_browser")

    stored=page.evaluate("""async()=>await new Promise((resolve,reject)=>{
      const r=indexedDB.open('vinto-off03a-profiles-v1',2);
      r.onerror=()=>reject(new Error('IDB open'));
      r.onsuccess=()=>{const db=r.result;const tx=db.transaction('scopes','readonly');
        const request=tx.objectStore('scopes').getAll();
        request.onsuccess=()=>{resolve(request.result);db.close()};
        request.onerror=()=>reject(new Error('IDB read'));
      };
    })""")
    assert len(stored)==1,stored
    assert stored[0]["sealed"]["format"]=="aes-gcm-v1"
    assert "VINTO-P1-18" not in json.dumps(stored)
    assert "private_key" not in json.dumps(stored)
    emit("03_only_encrypted_scope_in_indexeddb")

    # A server-signing-key rotation without an approved local re-enrolment
    # is forbidden and must not destroy the previously pinned scope.
    state["rotated"]=True
    page.reload(wait_until="domcontentloaded")
    page.get_by_text("Perfil local preparado.",exact=False).wait_for(timeout=60000)
    page.get_by_placeholder("MP1, MP3").fill("MP1")
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button",name="Guardar alcance firmado cifrado").click()
    page.get_by_text("No se guardó un alcance nuevo.",exact=False).wait_for(timeout=60000)
    emit("04_unapproved_public_key_rotation_denied")

    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller",timeout=60000)
    ctx.close()
    emit("05_chrome_process_closed")

    ctx=open_ctx(pw.chromium,path)
    ctx.set_offline(True)
    page=ctx.new_page()
    page.set_default_timeout(60000)
    response=page.goto(BASE+"/",wait_until="domcontentloaded",timeout=60000)
    assert response and response.status==200
    assert page.title()=="VINTO | Sin conexión"
    page.get_by_text("Perfil local preparado.",exact=False).wait_for(timeout=60000)
    pwd=page.locator("#offline-unlock-secret")
    pwd.fill("wrong synthetic passphrase")
    page.locator("#offline-unlock-submit").click()
    page.get_by_text("No fue posible desbloquear o validar",exact=False).wait_for(timeout=60000)
    assert page.locator("#offline-scope-list").is_hidden()
    emit("06_offline_wrong_phrase_no_scope")

    pwd.fill(SECRET)
    page.locator("#offline-unlock-submit").click()
    page.get_by_text("Firma y perfil verificados sin Internet.",exact=False).wait_for(timeout=60000)
    li=page.locator("#offline-scope-list li")
    assert li.count()==1
    assert li.first.inner_text()=="MP1 — VINTO-P1-18 (v3)"
    assert page.get_by_text("Las capturas y los permisos industriales siguen deshabilitados.",exact=False).count()>=1
    emit("07_offline_verified_signed_scope_read_only")

    screenshot=os.environ.get("OFF03B3_SCREENSHOT")
    if screenshot:
      page.screenshot(path=screenshot,full_page=True)
      emit("08_evidence_screenshot",file=Path(screenshot).name)

    # Corrupt encrypted ciphertext while offline: on next unlock it must NOT
    # show a verified grant or stale read-only forms.
    page.evaluate("""async()=>await new Promise((resolve,reject)=>{
      const r=indexedDB.open('vinto-off03a-profiles-v1',2);
      r.onerror=()=>reject(new Error('db'));
      r.onsuccess=()=>{const db=r.result,tx=db.transaction('scopes','readwrite'),
        s=tx.objectStore('scopes'),g=s.getAll();
        g.onsuccess=()=>{
          const row=g.result[0],v=row.sealed.ciphertext;
          row.sealed.ciphertext=(v[0]==='A'?'B':'A')+v.slice(1);
          s.put(row);
        };
        tx.oncomplete=()=>{db.close();resolve(true)};
        tx.onerror=()=>{db.close();reject(new Error('write'))};
      };
    })""")
    page.reload(wait_until="domcontentloaded")
    page.get_by_text("Perfil local preparado.",exact=False).wait_for(timeout=60000)
    page.locator("#offline-unlock-secret").fill(SECRET)
    page.locator("#offline-unlock-submit").click()
    page.get_by_text("No fue posible desbloquear o validar",exact=False).wait_for(timeout=60000)
    assert page.locator("#offline-scope-list").is_hidden()
    emit("09_tampered_encrypted_scope_fail_closed")
    ctx.close()
print("OFF03B3_BROWSER_SIGNED_SCOPE=PASS",flush=True)
