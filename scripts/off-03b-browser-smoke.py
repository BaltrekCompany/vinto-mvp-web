#!/usr/bin/env python3
"""OFF-03B.1: demo online-enrolment and offline unlock on Chrome persistent profile.

The test MOCKS /api/auth/me only for a synthetic user. It proves UI/IDB mechanics,
not a signed server grant nor any authority to capture industrial data.
"""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE=os.environ.get("OFF03B_BASE_URL","http://localhost:5173")
SECRET="VINTO offline synthetic qa phrase 182#!"
TEST_USER="11111111-1111-4111-8111-111111111111"

def report(name,**kwargs):
    print(json.dumps({"case":name,"result":"PASS",**kwargs},ensure_ascii=False),flush=True)

def context(browser,profile):
    return browser.launch_persistent_context(user_data_dir=str(profile),headless=True,channel="chrome",
         args=["--no-sandbox","--disable-dev-shm-usage"],service_workers="allow")

with tempfile.TemporaryDirectory(prefix="vinto-off03b-browser-") as tmp:
  profile=Path(tmp)/"profile"
  with sync_playwright() as pw:
    ctx=context(pw.chromium,profile)
    page=ctx.new_page()
    page.set_default_timeout(45000)
    origin=BASE.rstrip("/")

    def reply(route):
        route.fulfill(status=200,
          headers={
            "Content-Type":"application/json",
            "Cache-Control":"no-store",
            "Access-Control-Allow-Origin":origin,
            "Access-Control-Allow-Credentials":"true"
          },
          body=json.dumps({"user":{"id":TEST_USER,"username":"synthetic.qa","display_name":"Synthetic QA",
              "profiles":["CALIDAD"],"permissions":["quality.capture"],"must_change":False}}))
    page.route("**/api/auth/me",reply)
    page.goto(BASE+"/offline-preparacion",wait_until="domcontentloaded",timeout=120000)
    page.get_by_text("Preparación de prueba: crea una clave local protegida",exact=False).wait_for(timeout=60000)
    inputs=page.locator('input[type="password"]')
    assert inputs.count()==2
    inputs.nth(0).fill(SECRET)
    inputs.nth(1).fill(SECRET)
    page.get_by_role("button",name="Preparar perfil local").click()
    page.get_by_text("Perfil preparado",exact=False).wait_for(timeout=60000)
    report("01_online_enrollment_mocked_authenticated_user")
    profile_count=page.evaluate("""async()=>await new Promise((resolve,reject)=>{
        const r=indexedDB.open('vinto-off03a-profiles-v1',2);
        r.onerror=()=>reject(new Error("idb open"));
        r.onsuccess=()=>{
          const db=r.result, tx=db.transaction("profiles","readonly");
          const count=tx.objectStore("profiles").count();
          count.onsuccess=()=>{resolve(count.result);db.close()};
          count.onerror=()=>reject(new Error("idb count"));
        }
    })""")
    assert profile_count==1,profile_count
    report("02_single_wrapped_local_profile",count=profile_count)
    # Ensure the PWA shell has installed the worker before closing the first Chrome process.
    page.wait_for_function("() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller",timeout=60000)
    ctx.close()
    report("03_chrome_closed")

    ctx=context(pw.chromium,profile)
    ctx.set_offline(True)
    page=ctx.new_page()
    page.set_default_timeout(60000)
    response=page.goto(BASE+"/",wait_until="domcontentloaded",timeout=60000)
    assert response is not None and response.status==200
    assert page.title()=="VINTO | Sin conexión",page.title()
    page.get_by_text("Perfil local preparado.",exact=False).wait_for(timeout=60000)
    report("04_reopen_offline_profile_found")
    input=page.locator("#offline-unlock-secret")
    input.fill("incorrect local passphrase")
    page.locator("#offline-unlock-submit").click()
    page.get_by_text("No fue posible desbloquear",exact=False).wait_for(timeout=60000)
    report("05_wrong_phrase_rejected")
    input.fill(SECRET)
    page.locator("#offline-unlock-submit").click()
    page.get_by_text("Perfil local verificado sin Internet.",exact=False).wait_for(timeout=60000)
    assert page.get_by_text("Las capturas y los permisos industriales siguen deshabilitados.",exact=False).count()>=1
    report("06_real_offline_unlock_prototype")
    screenshot=os.getenv("OFF03B_SCREENSHOT")
    if screenshot:
      page.screenshot(path=screenshot,full_page=True)
      report("07_screenshot",file=Path(screenshot).name)
    ctx.close()
print("OFF03B_BROWSER_PROTOTYPE=PASS",flush=True)
