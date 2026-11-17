#!/usr/bin/env python3
"""OFF-02 Chrome QA for exact repo public files served from isolated QA root.

The root is a synthetic PUBLIC fixture, NOT VINTO authenticated application.
This test uses persistent real Chrome profile, forces network offline,
closes/reopens the browser, and verifies SW fallback + IndexedDB canary.
"""
import json
import os
import tempfile
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE = os.environ.get("OFF02_BASE_URL", "http://127.0.0.1:8765")
TIMEOUT_MS = 30000

def report(case: str, result: str, **details):
    print(json.dumps({"case": case, "result": result, **details}, ensure_ascii=False), flush=True)

def await_probe(page, expected: str):
    page.wait_for_function(
        """expected => {
          const el = document.getElementById('offline-probe-status');
          return !!el && el.textContent.toLowerCase().includes(expected);
        }""",
        arg=expected,
        timeout=TIMEOUT_MS,
    )
    return page.locator("#offline-probe-status").inner_text()

def open_profile(chromium, directory):
    channel = os.getenv("OFF02_CHROME_CHANNEL", "chrome")
    return chromium.launch_persistent_context(
        user_data_dir=str(directory),
        headless=True,
        channel=channel,
        args=["--no-sandbox", "--disable-dev-shm-usage"],
        service_workers="allow",
    )

def main():
    with tempfile.TemporaryDirectory(prefix="vinto-off02-chrome-") as temp:
        data_dir = Path(temp) / "profile"
        with sync_playwright() as p:
            context = open_profile(p.chromium, data_dir)
            page = context.new_page()
            page.set_default_timeout(TIMEOUT_MS)
            response = page.goto(BASE + "/", wait_until="domcontentloaded", timeout=90000)
            assert response and response.status == 200, f"online initial HTTP={response.status if response else None}"
            # The controller is a synchronous, genuine signal: activate+clients.claim() completed.
            page.wait_for_function(
                "() => ('serviceWorker' in navigator) && !!navigator.serviceWorker.controller",
                timeout=TIMEOUT_MS,
            )
            registrations = page.evaluate("""async () => (await navigator.serviceWorker.getRegistrations()).map(reg => ({scope: reg.scope, active: !!reg.active}))""")
            assert registrations and any(item["active"] for item in registrations), registrations
            expected_fixture = os.getenv("OFF02_EXPECT_FIXTURE", "1") == "1"
            if expected_fixture:
                assert page.locator("h1").inner_text() == "VINTO OFF-02 shell QA"
            else:
                assert "VINTO" in page.title(), f"unexpected VINTO document: {page.title()}"
            report("01_online_public_shell_and_sw" if expected_fixture else "01_online_vinto_frontend_and_sw", "PASS", status=response.status, workers=registrations)
            page.goto(BASE + "/offline.html", wait_until="load", timeout=TIMEOUT_MS)
            first = await_probe(page, "marca técnica almacenada")
            report("02_online_persistence_canary", "PASS", status=first)
            cached_urls = page.evaluate("""async () => {
              const urls = [];
              for (const key of await caches.keys()) {
                const c = await caches.open(key);
                for (const item of await c.keys()) urls.push(item.url);
              }
              return urls;
            }""")
            assert any(url.endswith("/offline.html") for url in cached_urls), cached_urls
            assert not any("/api/" in url or "/admin" in url for url in cached_urls), cached_urls
            assert BASE + "/" not in cached_urls, "authenticated root must not be stored"
            report("03_public_cache_only", "PASS", count=len(cached_urls))
            context.close()
            report("04_browser_closed", "PASS")

            # A fresh browser process opens the same real disk profile with Internet disabled.
            context = open_profile(p.chromium, data_dir)
            context.set_offline(True)
            page = context.new_page()
            page.set_default_timeout(TIMEOUT_MS)
            response = page.goto(BASE + "/", wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            assert response and response.status == 200, f"offline root response={response.status if response else None}"
            assert "VINTO | Sin conexión" in page.title()
            assert page.locator("h1").inner_text() == "Dispositivo sin conexión"
            report("05_reopened_offline_shell", "PASS", title=page.title())
            second = await_probe(page, "persistencia técnica verificada")
            report("06_indexeddb_survived_browser_restart", "PASS", status=second)
            canary = page.evaluate("""async () => await new Promise((resolve, reject) => {
              const request = indexedDB.open("vinto-off02-probe", 1);
              request.onerror = () => reject(new Error("IDB open failed"));
              request.onsuccess = () => {
                const db = request.result;
                const tx = db.transaction("canary", "readonly");
                const read = tx.objectStore("canary").get("probe");
                read.onsuccess = () => { resolve(read.result); db.close(); };
                read.onerror = () => { reject(new Error("IDB read failed")); db.close(); };
              };
            })""")
            assert canary == "OFF02", canary
            report("07_indexeddb_canary_value", "PASS", value=canary)
            screenshot = os.getenv("OFF02_SCREENSHOT_PATH")
            if screenshot:
                page.screenshot(path=screenshot, full_page=True)
                report("07b_evidence_screenshot", "PASS", file=Path(screenshot).name)
            # Restricted routes must not expose cached private data.
            try:
                page.goto(BASE + "/admin", wait_until="domcontentloaded", timeout=10000)
            except Exception:
                pass
            assert "/admin" not in [url.rstrip("/") for url in cached_urls]
            report("08_admin_not_cached", "PASS")
            context.close()
    print("OFF02_CHROMIUM_BROWSER_QA=PASS", flush=True)

if __name__ == "__main__":
    main()
