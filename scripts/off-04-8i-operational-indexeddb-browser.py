#!/usr/bin/env python3
"""OFF-04.8I isolated real Chrome test of operational encrypted IndexedDB.

Serves only a disposable public directory on 127.0.0.1; NO API, NO production
connection, NO real users/data, NO migration. Requires OFFLINE_DRAFT_LAB=1 build.
"""
import functools
import http.server
import json
import os
import tempfile
import threading
from pathlib import Path
from playwright.sync_api import sync_playwright

PUBLIC = Path(os.environ.get("OFF06B_PUBLIC", str(Path(__file__).resolve().parents[1] / "public")))
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
OWNER = "11111111-1111-4111-8111-111111111111"
DEVICE = "33333333-3333-4333-8333-333333333333"
DRAFT = "44444444-4444-4444-8444-444444444444"
CAPTURE = "55555555-5555-4555-8555-555555555555"
SCOPE = "66666666-6666-4666-8666-666666666666"
PASS = "VINTO OFF048I disposable QA password 8877!!"
class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

def invoke(page, name, argument=None):
    return page.evaluate("async ({name,arg}) => await window.VINTO_OFF048I[name](...(arg===null?[]:arg))",
                         {"name": name, "arg": argument})

def result(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)

if __name__ == "__main__":
    assert (PUBLIC / "off048i-indexeddb.html").is_file(), "build OFFLINE_DRAFT_LAB=1 first"
    handler = functools.partial(QuietHandler, directory=str(PUBLIC))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}/off048i-indexeddb.html"
    try:
        with tempfile.TemporaryDirectory(prefix="vinto-off048i-") as profile, sync_playwright() as pw:
            kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
            ctx = pw.chromium.launch_persistent_context(profile, headless=True,
                   args=["--no-sandbox", "--disable-dev-shm-usage"], **kwargs)
            page = ctx.new_page()
            assert page.goto(url, wait_until="load").status == 200
            invoke(page, "enroll", [OWNER, DEVICE, PASS])
            a = {"id": DRAFT, "revision": 1, "expectedRevision": None,
                 "scopeId": SCOPE, "formCode": "VINTO-P1-22", "formVersion": 2,
                 "machineCode": "MP1", "content": {"test": "synthetic QA value"}}
            assert invoke(page, "saveDraft", [a])["revision"] == 1
            first = invoke(page, "inspect")
            assert len(first["drafts"]) == 1
            assert "synthetic QA value" not in json.dumps(first)
            assert invoke(page, "openDraft", [DRAFT])["payload"]["test"] == "synthetic QA value"
            result("01_encrypted_draft_is_persisted_without_plaintext")

            # Close tab while database retains its contents, then reopen same origin.
            page.close()
            page = ctx.new_page()
            assert page.goto(url, wait_until="load").status == 200
            invoke(page, "unlock", [PASS])
            assert invoke(page, "openDraft", [DRAFT])["revision"] == 1
            result("02_draft_survives_page_close_and_reopen")

            # Revise with optimistic CAS and reject stale revisions.
            a.update(revision=2, expectedRevision=1, content={"test": "last synthetic revision"})
            assert invoke(page, "saveDraft", [a])["revision"] == 2
            try:
                invoke(page, "saveDraft", [a])
                raise AssertionError("stale CAS must fail")
            except Exception as error:
                assert "CONFLICT" in str(error)
            result("03_revision_CAS_rejects_stale_write")

            # Atomic one-click confirmation queues in the same IndexedDB transaction.
            c = {"draftId": DRAFT, "captureId": CAPTURE, "revision": 2}
            confirmed = invoke(page, "confirm", [c])
            assert confirmed == {"created": True, "captureId": CAPTURE}, confirmed
            state = invoke(page, "inspect")
            assert len(state["drafts"]) == len(state["pending"]) == len(state["queue"]) == 1
            assert state["drafts"][0]["frozenBy"] == CAPTURE
            assert state["queue"][0]["state"] == "queued"
            assert invoke(page, "openPending", [CAPTURE])["synthetic"] is False
            result("04_atomic_freeze_pending_queue_and_encrypted_open")

            # Repeat confirmation is idempotent with no second pending.
            assert invoke(page, "confirm", [c])["created"] is False
            state = invoke(page, "inspect")
            assert len(state["pending"]) == len(state["queue"]) == 1
            result("05_duplicate_confirmation_does_not_duplicate_queue")

            # Distinct tab racing for one capture id gets one lease.
            page2 = ctx.new_page()
            assert page2.goto(url, wait_until="load").status == 200
            invoke(page2, "unlock", [PASS])
            claims = [invoke(page, "claim", [CAPTURE, "tab-a"]),
                      invoke(page2, "claim", [CAPTURE, "tab-b"])]
            assert sum(x is not None for x in claims) == 1, claims
            assert invoke(page2, "finalize", [CAPTURE, "tab-b"]) is False
            assert invoke(page, "finalize", [CAPTURE, "tab-a"]) is True
            result("06_concurrent_tabs_one_lease_owner")

            # Restart entire browser profile. Nothing stored is purged.
            ctx.close()
            ctx = pw.chromium.launch_persistent_context(profile, headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"], **kwargs)
            page = ctx.new_page()
            assert page.goto(url, wait_until="load").status == 200
            invoke(page, "unlock", [PASS])
            state = invoke(page, "inspect")
            assert state["drafts"][0]["frozenBy"] == CAPTURE
            assert len(state["pending"]) == len(state["queue"]) == 1
            assert state["queue"][0]["state"] == "synced"
            result("07_browser_restart_retains_pending_and_queue_evidence")
            ctx.close()
        print("OFF04_8I_CHROME_INDEXEDDB=PASS", flush=True)
    finally:
        server.shutdown()
        server.server_close()
