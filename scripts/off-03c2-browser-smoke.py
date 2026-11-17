#!/usr/bin/env python3
"""OFF-03C.2 real Chrome: synthetic signed full form definition, AES, restart.

Mocked auth / scope / quality-package only; Python uses actual backend signing.
No live user or real capture and no productive PostgreSQL.
"""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright
from off03b3_fixture import USER_ID, sign_for_device, synthetic_quality_package

BASE=os.environ["OFF03C2_BASE_URL"]
SECRET="VINTO OFF03C2 browser synthetic secret 3498!!"

def report(name):
    print(json.dumps({"case":name,"result":"PASS"}),flush=True)

with tempfile.TemporaryDirectory(prefix="vinto-off03c2-") as tmp:
  profile_path=Path(tmp)/"browser"
  with sync_playwright() as pw:
    def chrome():
      return pw.chromium.launch_persistent_context(user_data_dir=str(profile_path),headless=True,channel="chrome",
         args=["--no-sandbox","--disable-dev-shm-usage"],service_workers="allow")
    ctx=chrome()
    page=ctx.new_page()
    page.set_default_timeout(60000)
    origin=BASE.rstrip("/")
    cors={"Access-Control-Allow-Origin":origin,"Access-Control-Allow-Credentials":"true",
          "Access-Control-Allow-Methods":"GET,POST,OPTIONS","Access-Control-Allow-Headers":"Content-Type"}
    state={}
    def mock(route):
      path=route.request.url
      if route.request.method=="OPTIONS":
        route.fulfill(status=204,headers=cors);return
      if "/api/auth/me" in path:
        data={"user":{"id":USER_ID,"username":"synthetic.quality","display_name":"Synthetic Quality",
                      "profiles":["CALIDAD"],"permissions":["quality.capture"],"must_change":False}}
      elif "/api/offline/quality-package" in path:
        request=json.loads(route.request.post_data)
        assert request["machine_code"]=="MP1" and request["form_code"]=="VINTO-P1-18"
        assert request["signed_scope"]==state["scope"]
        data=synthetic_quality_package(state["scope"])
      elif "/api/offline/scope" in path:
        request=json.loads(route.request.post_data)
        assert request["machine_codes"]==["MP1"]
        state["scope"]=sign_for_device(request["device_key"])
        data=state["scope"]
      else:
        raise AssertionError("Unexpected URL: "+path)
      route.fulfill(status=200,headers={"Content-Type":"application/json","Cache-Control":"no-store",**cors},
                    body=json.dumps(data,ensure_ascii=False))
    for endpoint in ("/api/auth/me","/api/offline/scope","/api/offline/quality-package"):
      page.route("**"+endpoint,mock)
    page.goto(BASE+"/offline-preparacion",wait_until="domcontentloaded",timeout=120000)
    page.get_by_text("Preparación de prueba: crea una clave local protegida",exact=False).wait_for(timeout=60000)
    page.locator('input[type="password"]').nth(0).fill(SECRET)
    page.locator('input[type="password"]').nth(1).fill(SECRET)
    page.get_by_role("button",name="Preparar perfil local").click()
    page.get_by_text("Perfil preparado",exact=False).wait_for(timeout=60000)
    report("01_synthetic_online_profile")

    page.get_by_placeholder("MP1, MP3").fill("MP1")
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button",name="Guardar alcance firmado cifrado").click()
    page.get_by_text("Alcance firmado verificado y guardado cifrado.",exact=False).wait_for(timeout=60000)
    report("02_signed_scope_verified_sealed")

    page.get_by_placeholder("MP1",exact=True).fill("MP1")
    page.get_by_placeholder("VINTO-P1-22").fill("VINTO-P1-18")
    page.locator('input[type="password"]').fill(SECRET)
    page.get_by_role("button",name="Guardar formulario firmado cifrado").click()
    page.get_by_text("Definición completa de Calidad firmada y guardada cifrada.",exact=False).wait_for(timeout=60000)
    report("03_full_definition_signed_and_encrypted")

    data=page.evaluate("""async()=>await new Promise((resolve,reject)=>{
      const r=indexedDB.open('vinto-off03a-profiles-v1',3);
      r.onerror=()=>reject(new Error('idb'));
      r.onsuccess=()=>{
        const db=r.result,tx=db.transaction('quality_packages','readonly');
        const req=tx.objectStore('quality_packages').getAll();
        req.onsuccess=()=>{resolve(req.result);db.close()};
        req.onerror=()=>reject(new Error('read'));
      };
    })""")
    assert len(data)==1,data
    assert data[0]["sealed"]["format"]=="aes-gcm-v1"
    assert "VINTO-P1-18" not in json.dumps(data)
    assert "Número de cuba" not in json.dumps(data,ensure_ascii=False)
    report("04_indexeddb_keeps_only_sealed_form")

    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller",timeout=60000)
    ctx.close()
    report("05_close_chrome")
    ctx=chrome()
    ctx.set_offline(True)
    page=ctx.new_page()
    page.set_default_timeout(60000)
    response=page.goto(BASE+"/",wait_until="domcontentloaded",timeout=60000)
    assert response and response.status==200
    page.get_by_text("Perfil local preparado.",exact=False).wait_for(timeout=60000)
    page.locator("#offline-unlock-secret").fill(SECRET)
    page.locator("#offline-unlock-submit").click()
    page.get_by_text("Firma y perfil verificados sin Internet.",exact=False).wait_for(timeout=60000)
    details=page.locator("#offline-package-details details")
    assert details.count()==1,details.count()
    details.first.locator("summary").click()
    assert details.first.get_by_text("Número de cuba",exact=False).is_visible()
    assert details.first.get_by_text("Masa húmeda g",exact=False).is_visible()
    assert page.locator("#offline-package-details input").count()==0
    assert page.get_by_text("Las capturas y los permisos industriales siguen deshabilitados.",exact=False).count()>=1
    report("06_read_only_complete_fields_after_offline_reopen")
    # OFF-03C.3: local-only QA on the same persistent Chrome profile, fully offline.
    page.get_by_role("button",name="Comprobar preparación técnica").click()
    page.locator("#offline-qa-checks li").first.wait_for(timeout=60000)
    checks=page.locator("#offline-qa-checks").inner_text()
    for name in ("Origen seguro", "Service Worker", "Recursos de apertura",
                 "Perfil único por navegador", "Alcance firmado almacenado",
                 "Paquete de Calidad almacenado"):
      assert "OK · "+name in checks,checks
    assert page.locator("#offline-qa-result").get_attribute("data-status") in ("warn","pass")
    assert USER_ID not in page.locator("#offline-qa-checks").inner_text()
    assert page.title()=="VINTO | Sin conexión"
    report("07_offline_device_preparation_diagnostic_read_only")


    screenshot=os.environ.get("OFF03C2_SCREENSHOT")
    if screenshot:
      page.screenshot(path=screenshot,full_page=True)
      report("08_screenshot_saved")

    page.evaluate("""async()=>await new Promise((resolve,reject)=>{
      const r=indexedDB.open('vinto-off03a-profiles-v1',3);
      r.onerror=()=>reject(new Error('db'));
      r.onsuccess=()=>{const db=r.result,tx=db.transaction('quality_packages','readwrite'),
        store=tx.objectStore('quality_packages'),get=store.getAll();
        get.onsuccess=()=>{
          const row=get.result[0],txt=row.sealed.ciphertext;
          row.sealed.ciphertext=(txt[0]==='A'?'B':'A')+txt.slice(1);
          store.put(row);
        };
        tx.oncomplete=()=>{db.close();resolve(true)};
        tx.onerror=()=>{db.close();reject(new Error('write'))};
      };
    })""")
    page.goto(BASE+"/offline.html",wait_until="domcontentloaded",timeout=60000)
    page.get_by_text("Perfil local preparado.",exact=False).wait_for(timeout=60000)
    page.locator("#offline-unlock-secret").fill(SECRET)
    page.locator("#offline-unlock-submit").click()
    page.get_by_text("No fue posible desbloquear o validar",exact=False).wait_for(timeout=60000)
    assert page.locator("#offline-package-details").is_hidden()
    assert page.locator("#offline-scope-list").is_hidden()
    report("09_tamper_package_ciphertext_fails_closed")
    ctx.close()
print("OFF03C2_BROWSER_QUALITY_PACKAGE=PASS",flush=True)
