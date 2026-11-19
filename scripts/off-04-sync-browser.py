#!/usr/bin/env python3
"""OFF-04.3 real-Chrome IndexedDB integration for the synchronisation engine (synthetic data, in-memory FAKE server only).

No backend, no real API, no network beyond loopback. The scenario suite (also run in Node) is executed against the
real IndexedDB queue store; then multi-tab, restart and storage-failure behaviour is checked directly.
"""
import http.server
import json
import os
import tempfile
import threading
import time
from pathlib import Path
from playwright.sync_api import sync_playwright

HARNESS = Path(os.environ["OFF04S_HARNESS_JS"]).read_bytes()
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
SECRET = "VINTO OFF043 synthetic sync secret 4410!!"
ID = {"ownerId": "11111111-1111-4111-8111-111111111111", "deviceKey": "33333333-3333-4333-8333-333333333333"}
requests_seen = []


def report(name):
    print(json.dumps({"case": name, "result": "PASS"}), flush=True)


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body, kind = (HARNESS, "text/javascript") if self.path == "/harness.js" else (
            b'<!doctype html><meta charset="utf-8"><title>off043</title><script src="/harness.js"></script>', "text/html")
        self.send_response(200)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
URL = f"http://localhost:{server.server_address[1]}/"


class Tab:
    def __init__(self, page):
        self.page = page

    def call(self, fn, *args):
        return self.page.evaluate("([f,a]) => window.H[f](...a)", [fn, list(args)])


class Browser:
    def __init__(self, pw, profile):
        self.pw, self.profile = pw, profile

    def open(self, unlock=True):
        kwargs = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
        self.ctx = self.pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], service_workers="block", **kwargs)
        self.ctx.on("request", lambda r: requests_seen.append(r.url))
        self.tab = self.new_tab(unlock)
        return self

    def new_tab(self, unlock=True):
        page = self.ctx.new_page()
        page.set_default_timeout(120000)
        page.goto(URL)
        page.wait_for_function("() => !!window.H")
        tab = Tab(page)
        if unlock:
            assert tab.call("unlock", SECRET) is True
        return tab

    def call(self, fn, *args):
        return self.tab.call(fn, *args)

    def kill(self):
        self.ctx.close()


def states(b):
    r = b.call("list")
    assert r["ok"], r
    return {x["id"]: x for x in r["rows"]}


with tempfile.TemporaryDirectory(prefix="vinto-off043-") as tmp, sync_playwright() as pw:
    # ---- 01 the whole scenario suite against the REAL IndexedDB store ----
    b = Browser(pw, Path(tmp) / "suite")
    b.open(unlock=False)
    b.call("enrol", ID, SECRET)
    assert b.call("unlock", SECRET) is True
    results = b.tab.page.evaluate("() => window.H.runScenarios()")
    failed = [r for r in results if not r["ok"]]
    assert not failed and len(results) >= 24, failed
    for r in results:
        report("suite_" + r["name"])
    b.kill()

    # ---- 02 two REAL tabs on one IndexedDB: each capture is claimed and sent exactly once ----
    b = Browser(pw, Path(tmp) / "tabs")
    b.open(unlock=False)
    b.call("enrol", ID, SECRET)
    assert b.call("unlock", SECRET) is True
    ids = b.call("addMany", 8)["ids"]
    tab2 = b.new_tab()
    for t in (b.tab, tab2):
        t.call("newServer", [], "ctx-1", 15)
        t.call("setSession", ID["ownerId"])
    race = [b.tab.call("claimRace", ids[0], "A"), tab2.call("claimRace", ids[0], "B")]      # sequential, but on the SAME stored lease
    assert [r["won"] for r in race].count(True) == 1, race
    b2 = Browser(pw, Path(tmp) / "tabs-b")                                                     # fresh browser, nothing shared
    b2.open(unlock=False)
    b2.call("enrol", ID, SECRET)
    assert b2.call("unlock", SECRET) is True
    assert states(b2) == {}
    b2.kill()
    ids2 = b.call("addMany", 8, 100)["ids"]
    start = "() => { window.__r = H.sync('%s'); }"
    b.tab.page.evaluate(start % "A")
    tab2.page.evaluate(start % "B")
    ra = b.tab.page.evaluate("async () => await window.__r"); rb = tab2.page.evaluate("async () => await window.__r")
    assert ra["ok"] and rb["ok"], (ra, rb)
    acc_a, acc_b = set(ra["accepted"]), set(rb["accepted"])
    assert not (acc_a & acc_b), "a capture was sent by BOTH tabs"
    sent_total = ra["sends"] + rb["sends"]
    done = [x for x in states(b).values() if x["state"] == "synced"]
    assert len(acc_a | acc_b) == sent_total == len(done), (sent_total, len(acc_a | acc_b), len(done))
    assert all(x["state"] in ("synced", "syncing", "queued") for x in states(b).values())
    report("02_two_real_tabs_never_send_a_capture_twice")
    b.kill()

    # ---- 03 persistent states survive closing the browser; interrupted work is recovered ----
    b = Browser(pw, Path(tmp) / "restart")
    b.open(unlock=False)
    b.call("enrol", ID, SECRET)
    assert b.call("unlock", SECRET) is True
    ids = b.call("addMany", 3)["ids"]
    b.call("newServer", [{"type": "network_before"}], "ctx-1")
    b.call("setSession", ID["ownerId"])
    r = b.call("sync", "A")
    assert r["ok"] and r["result"]["stopped"] == "network", r
    before = states(b)
    assert [before[i]["state"] for i in ids] == ["retry_wait", "queued", "queued"] and before[ids[0]]["uncertain"] is True
    b.kill()
    b.open()
    after = states(b)
    assert {k: (v["state"], v["attempts"], v["uncertain"]) for k, v in after.items()} == {k: (v["state"], v["attempts"], v["uncertain"]) for k, v in before.items()}
    time.sleep(1.2)                                                                              # backoff (300 ms base) elapsed
    b.call("newServer", [], "ctx-1")
    b.call("setSession", ID["ownerId"])
    r = b.call("sync", "A2")
    assert r["ok"] and r["result"]["counts"]["synced"] == 3, r
    assert [s["state"] for s in states(b).values()] == ["synced"] * 3
    report("03_states_survive_restart_and_resume")

    # ---- 04 storage failures never lose a record or half-apply a result ----
    ids = b.call("addMany", 1, 200)["ids"]
    b.call("newServer", [], "ctx-1"); b.call("setSession", ID["ownerId"])
    b.call("failPutOn", 1, "QuotaExceededError")                                                 # the CLAIM cannot be stored
    r = b.call("sync", "A3")
    b.call("clearFaults")
    assert r["ok"] is False, r
    assert states(b)[ids[0]]["state"] == "queued" and b.call("serverSends") == 0
    b.call("failPutOn", 2)                                                                       # claim ok, the RESULT cannot be stored
    r = b.call("sync", "A4")
    b.call("clearFaults")
    assert r["ok"] is False, r
    st = states(b)[ids[0]]
    assert st["state"] == "syncing" and st["hasLease"] is True and b.call("serverAccepted") == 1   # persisted centrally, still "syncing" locally
    raw = b.call("raw")
    lease = [x for x in raw if x["capture_id"] == ids[0]][0]["lease"]
    assert lease["until"] > 0
    report("04_storage_failures_leave_a_recoverable_state")
    b.kill()

    # ---- 05 no real API, no network ----
    b = Browser(pw, Path(tmp) / "net")
    b.open(unlock=False)
    b.call("enrol", ID, SECRET)
    assert b.call("unlock", SECRET) is True
    b.call("addMany", 2); b.call("newServer", [], "ctx-1"); b.call("setSession", ID["ownerId"]); b.call("sync", "A")
    assert b.call("networkAttempts") == []
    assert all(u.startswith(URL.rstrip("/")) or u.startswith("data:") or u.startswith("about:") for u in requests_seen), [u for u in requests_seen if not u.startswith(URL.rstrip("/"))]
    assert not any("/api/" in u for u in requests_seen)
    report("05_no_real_api_or_network_request")
    b.kill()
print("OFF04_3_SYNC_ENGINE_CHROME=PASS", flush=True)
