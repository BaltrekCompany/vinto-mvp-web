#!/usr/bin/env python3
"""OFF-04.8 v6 (Issue #247) REAL-Chrome test of the CAPTURE reuse / coalescing, against a DISPOSABLE loopback stub of the QA API that signs with the REAL backend signer (readiness scope,
quality packages, CAPTURE authority). No deployed service, database, secret or production data is contacted. Everything synthetic.

  1. (optional, OFF048V_V5_PUBLIC) the v5 PWA is installed and prepared, a DRAFT is saved; v6 is published; after the upgrade (a few online loads) the cache is v6, offline works, and every IndexedDB
     database is byte-identical (nothing deleted) and the draft is still listed after the unlock.
  2. first preparation: 10/10 definitions, exactly ONE POST /capture-scope.
  3. login/unlock/online BURST with nothing changed: no further POST /capture-scope (reuse or cooldown), at most one preparation in flight.
  4. a grant revoked (P1-22 removed): the burst issues exactly ONE new authority, 9/9 forms; the revoked pair is not offered.
  5. short-lived authority (< 8 h): never reused (a new one every manual retry); the 24 h one is reused again afterwards.
  6. a failed preparation (package 500) leaves every IndexedDB database byte-identical; the manual retry works afterwards and skips the cooldown.
Usage: OFF06B_PUBLIC=<dir built with OFFLINE_OPERATIONAL_CAPTURE=1> [OFF048V_V5_PUBLIC=<v5 dir>] [OFF04_CHROME_CHANNEL=bundled] python scripts/off-04-8v-reuse-browser.py"""
import hashlib, http.server, json, os, shutil, sys, tempfile, threading, time, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from off03b3_fixture import USER_ID, signer  # noqa: E402  (also puts backend on sys.path)
from off048t_fixture import VERSIONS, sign_package  # noqa: E402
from app.offline_scope.signing import sign_scope  # noqa: E402
from app.qa_pilot_auth import synthetic_definition  # noqa: E402
from app.quality.offline_capture_authority import _signed  # noqa: E402
from app.quality.offline_capture_scope import AUDIENCE as CAP_AUD, KIND as CAP_KIND, SCHEMA as CAP_SCHEMA  # noqa: E402
from app.offline_scope.signing import AUDIENCE as RD_AUD, ISSUER, SCHEMA as RD_SCHEMA  # noqa: E402

PUBLIC = Path(os.environ.get("OFF06B_PUBLIC", str(HERE.parent / "public")))
V5 = os.environ.get("OFF048V_V5_PUBLIC")
CHANNEL = os.environ.get("OFF04_CHROME_CHANNEL", "chrome")
SECRET = "VINTO OFF048V disposable local passphrase 4471!!"
BOBBIN = {"VINTO-P1-19", "VINTO-P1-20", "VINTO-P1-21", "VINTO-P1-24", "VINTO-P1-25", "VINTO-P1-28"}
res = []


def rep(name, cond, detail=""):
    res.append(bool(cond)); print(json.dumps({"case": name, "result": "PASS" if cond else "FAIL", "detail": str(detail)[:300]}), flush=True)


def uid4(*parts): return str(uuid.UUID(bytes=hashlib.sha256("|".join(parts).encode()).digest()[:16], version=4))
def iso(d): return d.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


class Stub:
    """Mutable loopback API. `ctl` is changed by the test through the Python object (same process)."""
    def __init__(self, pub):
        self.pub, self.lock = pub, threading.Lock()
        self.forms = dict(VERSIONS); self.grants = {f: uid4("grant", f) for f in VERSIONS}
        self.ttl_h = 24; self.fail_package = False; self.last_issued = None; self.rev = 0; self.cached_scope = None; self.cached_rev = -1
        self.counts = {"scope": 0, "package": 0, "capture-scope": 0, "login": 0, "me": 0}
        self.log = []

    def pairs(self):
        return [{"machine_code": "MP1", "form_code": f, "form_version": v, "grant_id": self.grants[f], "operation": "quality_bobbin_capture" if f in BOBBIN else "quality_machine_capture"}
                for f, v in sorted(self.forms.items())]

    def change(self): self.rev += 1

    def scope(self, device):
        if self.cached_rev == self.rev and self.cached_scope is not None and self.cached_scope["payload"]["device_key"] == device: return self.cached_scope
        now = datetime.now(timezone.utc).replace(microsecond=0)
        if self.last_issued and now <= self.last_issued: now = self.last_issued + timedelta(seconds=1)
        self.last_issued = now
        payload = {"schema": RD_SCHEMA, "issuer": ISSUER, "audience": RD_AUD, "snapshot_id": str(uuid.uuid4()), "subject_user_id": USER_ID, "device_key": device, "issued_at": iso(now),
                   "kind": "scope_readiness_only", "captures_enabled": False, "form_scopes": self.pairs()}
        self.cached_scope, self.cached_rev = sign_scope(payload, signer=signer(False)), self.rev
        return self.cached_scope


def make_handler(stub):
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(s, *a, **k): super().__init__(*a, directory=str(stub.pub), **k)
        def log_message(s, *a): pass
        def end_headers(s): s.send_header("Cache-Control", "no-cache"); super().end_headers()
        def _json(s, status, body, cookie=None):
            raw = json.dumps(body).encode(); s.send_response(status); s.send_header("Content-Type", "application/json"); s.send_header("Content-Length", str(len(raw)))
            if cookie: s.send_header("Set-Cookie", cookie)
            s.end_headers(); s.wfile.write(raw)
        def _auth(s): return "sid=ok" in (s.headers.get("Cookie") or "")
        def _body(s):
            n = int(s.headers.get("Content-Length") or 0); return json.loads(s.rfile.read(n) or b"{}")
        USER = {"user": {"id": USER_ID, "username": "qa.synthetic", "display_name": "QA sintético", "profiles": ["CALIDAD"], "permissions": ["quality.capture"], "must_change": False}}
        def do_GET(s):
            if s.path == "/api/auth/me":
                with stub.lock: stub.counts["me"] += 1
                return s._json(200, s.USER) if s._auth() else s._json(401, {"detail": "no"})
            if s.path.startswith("/api/"): return s._json(404, {"detail": "no"})
            super().do_GET()
        def do_POST(s):
            b = s._body()
            with stub.lock:
                if s.path == "/api/auth/login":
                    stub.counts["login"] += 1; return s._json(200, s.USER, cookie="sid=ok; Path=/; HttpOnly")
                if not s._auth(): return s._json(401, {"detail": "no"})
                if s.path == "/api/offline/scope":
                    stub.counts["scope"] += 1; return s._json(200, stub.scope(b["device_key"]))
                if s.path == "/api/offline/quality-package":
                    stub.counts["package"] += 1
                    if stub.fail_package: return s._json(500, {"detail": "boom"})
                    sc = b["signed_scope"]; item = next(x for x in sc["payload"]["form_scopes"] if x["form_code"] == b["form_code"])
                    return s._json(200, sign_package(sc, b["machine_code"], b["form_code"], synthetic_definition(b["form_code"], item["form_version"]), label="v6"))
                if s.path == "/api/offline/capture-scope":
                    stub.counts["capture-scope"] += 1
                    now = datetime.now(timezone.utc).replace(microsecond=0); exp = now + timedelta(hours=stub.ttl_h)
                    payload = {"schema": CAP_SCHEMA, "issuer": "vinto-backend", "audience": CAP_AUD, "kind": CAP_KIND, "snapshot_id": str(uuid.uuid4()), "subject_user_id": USER_ID,
                               "device_key": b["device_key"], "issued_at": iso(now), "expires_at": iso(exp), "form_scopes": stub.pairs()}
                    return s._json(200, _signed(payload, signer(False)))
            s._json(404, {"detail": "no"})
    return H


IDB_DUMP = """async () => { const out = {}; for (const d of await indexedDB.databases()) { const db = await new Promise((r, j) => { const q = indexedDB.open(d.name); q.onsuccess = () => r(q.result); q.onerror = () => j(q.error); });
  const stores = {}; for (const n of [...db.objectStoreNames]) { const rows = await new Promise((r, j) => { const q = db.transaction(n).objectStore(n).getAll(); q.onsuccess = () => r(q.result); q.onerror = () => j(q.error); });
    const keys = await new Promise((r, j) => { const q = db.transaction(n).objectStore(n).getAllKeys(); q.onsuccess = () => r(q.result); q.onerror = () => j(q.error); });
    const enc = new TextEncoder().encode(JSON.stringify([keys, rows], (k, v) => v instanceof ArrayBuffer ? Array.from(new Uint8Array(v)) : ArrayBuffer.isView(v) ? Array.from(new Uint8Array(v.buffer, v.byteOffset, v.byteLength)) : v));
    const h = new Uint8Array(await crypto.subtle.digest('SHA-256', enc)); stores[n] = [rows.length, Array.from(h.slice(0, 8), x => x.toString(16).padStart(2, '0')).join('')]; }
  db.close(); out[d.name] = stores; } return out; }"""


def main():
    tmp = Path(tempfile.mkdtemp(prefix="off048v-")); pub = tmp / "public"; pub.mkdir()
    def publish(src):
        for f in pub.iterdir(): f.unlink()
        for f in Path(src).iterdir():
            if f.is_file() and f.name != "SHA256SUMS": shutil.copy(f, pub / f.name)
    stub = Stub(pub); srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), make_handler(stub)); threading.Thread(target=srv.serve_forever, daemon=True).start()
    origin = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        with sync_playwright() as pw:
            kw = {"channel": CHANNEL} if CHANNEL != "bundled" else {}
            ctx = pw.chromium.launch_persistent_context(user_data_dir=str(tmp / "profile"), headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"], service_workers="allow", **kw)
            def open_page(offline=False):
                ctx.set_offline(offline); p = ctx.new_page(); p.set_default_timeout(45000); r = p.goto(origin + "/offline-calidad.html", wait_until="load"); p.wait_for_timeout(800); return p, r
            def status(p): return p.locator("#status").inner_text()
            def wait_ready(p, n):
                try: p.wait_for_function("n => document.getElementById('status').textContent.includes('(' + n + ' de ' + n + ')')", arg=n, timeout=60000)
                except Exception: print("STATUS_AT_TIMEOUT:", status(p), stub.counts, flush=True); raise
            def unlock(p): p.fill("#unlock-secret", SECRET); p.click("#unlock button[type=submit]")
            def burst(p, n=6):  # unlock + repeated `online` events + a second unlock-less trigger, like login/unlock/reconnect arriving together
                unlock(p)
                for _ in range(n): p.evaluate("window.dispatchEvent(new Event('online'))"); p.wait_for_timeout(120)
            def settle(p, n):
                wait_ready(p, n); p.wait_for_timeout(1500)
            def first_prepare():
                publish(V5 if V5 else PUBLIC)
                p, _ = open_page()
                if not p.locator("#login-panel").is_hidden():
                    p.fill("#username", "qa.synthetic"); p.fill("#password", "synthetic-pass-0000"); p.click("#login button[type=submit]")
                p.wait_for_selector("#prepare-panel:not([hidden])"); p.fill("#machine", "MP1"); p.fill("#passphrase", SECRET); p.click("#prepare button[type=submit]")
                wait_ready(p, 10); return p
            # ---- first preparation (v5 build when available: the upgrade case)
            p = first_prepare()
            rep("first preparation: 10 of 10 definitions", p.locator("#form option").count() == 10, status(p))
            rep("first preparation: exactly ONE POST /capture-scope", stub.counts["capture-scope"] == 1, stub.counts)
            if V5:
                p.select_option("#form", index=4); p.click("#new"); p.wait_for_selector("#editor:not([hidden])")
                first = p.locator("#fields input, #fields select, #fields textarea").first; first.fill("1") if first.get_attribute("type") != "checkbox" else first.check()
                p.wait_for_timeout(1500); p.click("#back"); p.wait_for_timeout(800)
                rep("v5: a draft was saved before the upgrade", p.locator("#drafts li").count() >= 1, p.locator("#drafts").inner_text()[:80])
                before = p.evaluate(IDB_DUMP); p.close()
                publish(PUBLIC); loads = 0; cache_ok = False
                for _ in range(8):
                    q, _ = open_page(); loads += 1; q.evaluate('navigator.serviceWorker.ready.then(() => true)'); q.wait_for_timeout(2000)
                    names = q.evaluate("async () => { const o = {}; for (const n of await caches.keys()) o[n] = (await (await caches.open(n)).keys()).map(r => new URL(r.url).pathname).sort(); return o; }")
                    cache_ok = "/offline-calidad.js" in names.get("vinto-off048-quality-static-v6", []) and "/offline-calidad.html" in names.get("vinto-off048-quality-static-v6", [])
                    print('LOAD', loads, {k: len(v) for k, v in names.items()}, flush=True); q.close()
                    if cache_ok: break
                rep(f"v5 -> v6: cache v6 holds the shell after {loads} online load(s)", cache_ok and loads <= 8)
                q, r = open_page(offline=True)
                rep("v6 offline: the page loads from the cache and shows the unlock panel", r is not None and r.status == 200 and q.locator("#unlock-panel").is_visible())
                after = q.evaluate(IDB_DUMP); rep("v5 -> v6: EVERY IndexedDB database is byte-identical (nothing deleted or rewritten)", before == after, json.dumps(after)[:200]); q.close()
                ctx.set_offline(False)
                n0 = stub.counts["capture-scope"]; p, _ = open_page(); unlock(p); settle(p, 10)
                rep("v6 after the upgrade: the unlock lists the draft saved by v5", p.locator("#drafts li").count() >= 1)
                rep("v6 after the upgrade: the stored v5 authority is REUSED (no new POST /capture-scope)", stub.counts["capture-scope"] == n0, stub.counts)
                p.close()
            # ---- burst, nothing changed
            n0, s0 = stub.counts["capture-scope"], stub.counts["scope"]; p, _ = open_page(); burst(p); settle(p, 10)
            rep("burst (unlock + 6 online events), nothing changed: NO new POST /capture-scope", stub.counts["capture-scope"] == n0, stub.counts)
            rep("burst: at most ONE preparation ran (scope reads)", stub.counts["scope"] - s0 <= 1, stub.counts["scope"] - s0)
            rep("burst: 10 of 10 offline-ready", "(10 de 10)" in status(p), status(p))
            # ---- revocation of P1-22
            del stub.forms["VINTO-P1-22"]; stub.change(); n0 = stub.counts["capture-scope"]; p.close(); p, _ = open_page(); burst(p); settle(p, 9)
            rep("grant revoked + burst: exactly ONE new POST /capture-scope", stub.counts["capture-scope"] == n0 + 1, stub.counts)
            rep("revoked pair is no longer offered (9 forms, no P1-22)", p.locator("#form option").count() == 9 and "P1-22" not in p.locator("#form").inner_text(), p.locator("#form").inner_text()[:120])
            # ---- short-lived authority is never reused; a 24 h one is
            def manual(p, wait=2500):   # the user's "Reintentar" (bypasses only the cooldown); the button is revealed because a user only sees it after a failure
                p.evaluate("() => { const b = document.getElementById('offline-retry'); b.hidden = false; b.click(); }"); p.wait_for_timeout(wait)
            stub.ttl_h = 7; stub.grants["VINTO-P1-18"] = uid4("grant", "VINTO-P1-18", "reissued"); stub.change(); n0 = stub.counts["capture-scope"]
            manual(p); manual(p)
            rep("grant re-issued + 7 h authority: issued on the first manual preparation and NEVER reused by the second", stub.counts["capture-scope"] - n0 == 2, stub.counts["capture-scope"] - n0)
            stub.ttl_h = 24; n0 = stub.counts["capture-scope"]; manual(p); manual(p); manual(p)
            rep("24 h authority: ONE issuance (the 7 h one is too short), then reused by the next manual preparations", stub.counts["capture-scope"] - n0 == 1, stub.counts["capture-scope"] - n0)
            rep("still 9 of 9 and no error after the manual preparations", "(9 de 9)" in status(p), status(p))
            # ---- an automatic trigger inside the cooldown does nothing; after a failure it is not blocked
            s0 = stub.counts["scope"]; p.evaluate("window.dispatchEvent(new Event('online'))"); p.wait_for_timeout(1500)
            rep("automatic `online` inside the 10 min cooldown (authority still valid): no preparation at all", stub.counts["scope"] == s0, stub.counts["scope"] - s0)
            # ---- failed preparation leaves every IndexedDB database untouched; manual retry works
            before = p.evaluate(IDB_DUMP); stub.fail_package = True; stub.change(); n0 = stub.counts["capture-scope"]
            manual(p, 3000)
            rep("failed preparation: readable message and retry button shown", "No se descargaron todos los formularios" in status(p) and p.locator("#offline-retry").is_visible(), status(p))
            rep("failed preparation: EVERY IndexedDB database byte-identical, no authority requested", p.evaluate(IDB_DUMP) == before and stub.counts["capture-scope"] == n0)
            stub.fail_package = False; p.click("#offline-retry"); p.wait_for_timeout(3000)
            rep("manual retry skips the cooldown and completes (9 of 9)", "(9 de 9)" in status(p), status(p))
            ctx.close()
    finally:
        srv.shutdown(); shutil.rmtree(tmp, ignore_errors=True)
    print(f"OFF048V_BROWSER checks={len(res)} fails={res.count(False)} stub={stub.counts}")
    return 0 if all(res) else 1


if __name__ == "__main__":
    sys.exit(main())
