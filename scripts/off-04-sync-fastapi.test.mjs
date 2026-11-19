// OFF-04.4: the OFF-04.3 engine against the isolated FastAPI receiver, through a DISPOSABLE loopback server (synthetic data only).
// The server is started by this test with its own throwaway SQLite file; nothing points at a deployed API.
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { test } from "node:test";
import { createLocalVault } from "../lib/vinto/offline-vault.ts";
import { syncNow, payloadHash } from "../lib/vinto/offline-sync-engine.ts";
import { createSyncCapture, openSyncPayload } from "../lib/vinto/offline-sync-capture.ts";
import { createHttpSyncTransport } from "../lib/vinto/offline-sync-http-transport.ts";
import { createMemorySyncStore } from "./off-04-sync-memory-store.ts";

const root = resolve(import.meta.dirname, "..");
const PY = process.env.OFF044_PYTHON || "python";
const A = "11111111-1111-4111-8111-111111111111", B = "22222222-2222-4222-8222-222222222222";
const SNAP_OK = "55555555-5555-4555-8555-555555555555", SNAP_CONSULT = "44444444-4444-4444-8444-444444444444";
const tmp = mkdtempSync(join(tmpdir(), "vinto-off044-"));

async function startServer(db, extra = []) {
    const child = spawn(PY, ["tests/off044_receiver_server.py", "--db", db, ...extra], { cwd: join(root, "backend"), stdio: ["pipe", "pipe", "pipe"] });
    const port = await new Promise((res, rej) => {
        let buf = "";
        const t = setTimeout(() => rej(new Error("receiver did not start: " + buf)), 30000);
        child.stdout.on("data", d => { buf += d; const m = /PORT=(\d+)/.exec(buf); if (m) { clearTimeout(t); res(Number(m[1])); } });
        child.on("exit", () => rej(new Error("receiver exited: " + buf)));
    });
    const url = "http://127.0.0.1:" + port;
    const post = async (path, body) => (await fetch(url + path, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) })).json();
    return {
        url, child,
        stop: () => new Promise(r => { child.once("exit", r); child.stdin.end(); setTimeout(() => child.kill(), 3000); }),
        stats: async () => (await fetch(url + "/__test__/stats")).json(),
        config: (c) => post("/__test__/config", c),
    };
}

const http = (base, user, hooks = {}) => async ({ method, path, body, signal }) => {
    const headers = { "content-type": "application/json" };
    if (user.v) headers["x-synthetic-user"] = user.v;
    const res = await fetch(base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), signal });
    const json = await res.json().catch(() => ({}));
    hooks.after?.(method, path, res.status);
    return { status: res.status, json };
};
const mkReq = async (captureId, over = {}) => {
    const payload = over.payload ?? { synthetic: true, payload: { numero_de_cuba: "C-1-SINT" } };
    return { capture_id: captureId, author_user_id: A, device_key: "33333333-3333-4333-8333-333333333333", form_code: "VINTO-P1-26", form_version: 1,
        machine_code: "MP1", scope_snapshot_id: SNAP_OK, context_version: "ctx-1", payload_sha256: await payloadHash(payload), payload, ...over };
};
const signal = () => new AbortController().signal;

test("engine against the isolated FastAPI receiver", async () => {
    const { key } = await createLocalVault({ ownerId: A, deviceKey: "99999999-9999-4999-8999-999999999999" }, "VINTO OFF044 synthetic secret 8123!!");
    const db = join(tmp, "main.sqlite");
    let srv = await startServer(db);
    let seq = 0;
    const clock = { t: 1_700_000_000_000 };
    const user = { v: A };
    const ctxOf = async (opts = {}) => {
        const identity = { ownerId: A, deviceKey: crypto.randomUUID() };
        const store = createMemorySyncStore();
        const posts = { n: 0 };
        const make = (hooks) => createHttpSyncTransport(http(opts.base ?? srv.url, opts.user ?? user, { after: (m, p, s) => { if (m === "POST") posts.n += 1; hooks?.(m, p, s); } }));
        const deps = (tab, extra = {}) => ({ store, transport: make(opts.hook), session: async () => (extra.sessionUser ?? A) ? { userId: extra.sessionUser ?? A } : null,
            openPayload: openSyncPayload(key, identity), identity, tabId: tab + crypto.randomUUID().slice(0, 4), now: () => clock.t, rand: () => 1,
            options: { leaseMs: 30000, timeoutMs: 5000, maxAttempts: 4, baseDelayMs: 1000, maxDelayMs: 60000 }, ...extra });
        const add = (n, extra = {}) => createSyncCapture(key, identity, store, { payload: { numero_de_cuba: "C-" + n + "-SINT" }, contextVersion: extra.contextVersion ?? "ctx-1",
            machineCode: "MP1", scopeSnapshotId: extra.snapshot ?? SNAP_OK, seq: ++seq }, () => clock.t);
        return { identity, store, posts, deps, add, run: (tab = "A", extra) => syncNow(deps(tab, extra)), rec: async (r) => store.get(r.capture_id) };
    };
    await srv.config({ grants: [[A, "MP1", "VINTO-P1-26"], [B, "MP1", "VINTO-P1-26"]], fail_next: 0 });
    const results = [];
    const scenario = async (name, fn) => {
        try { try { await srv.config({ grants: [[A, "MP1", "VINTO-P1-26"], [B, "MP1", "VINTO-P1-26"]], fail_next: 0 }); } catch { /* this scenario uses another server */ } user.v = A; await fn(); results.push([name, true]); }
        catch (e) { results.push([name, false, String(e.message).slice(0, 300)]); }
    };

    await scenario("01 first receipt is synced only after a verified central confirmation", async () => {
        const c = await ctxOf(); const a = await c.add(1);
        const before = (await srv.stats()).receipts;
        const r = await c.run();
        assert.deepEqual([r.sent, r.counts.synced], [1, 1]);
        const s = await c.rec(a);
        assert.ok(/^srv-\d+$/.test(s.serverRef) && s.state === "synced" && s.capture_id === a.capture_id);
        assert.equal((await srv.stats()).receipts, before + 1);
    });
    await scenario("02 identical duplicate is idempotent (200 duplicate, same server id)", async () => {
        const tr = createHttpSyncTransport(http(srv.url, user)); const id = crypto.randomUUID(); const req = await mkReq(id);
        const r1 = await tr.send(req, { signal: signal() }); const r2 = await tr.send(req, { signal: signal() });
        assert.deepEqual([r1.status, r1.body.outcome, r2.status, r2.body.outcome], [201, "created", 200, "duplicate"]);
        assert.equal(r1.body.server_id, r2.body.server_id);
    });
    await scenario("03 same id with different content is a conflict and the original is kept", async () => {
        const tr = createHttpSyncTransport(http(srv.url, user)); const id = crypto.randomUUID();
        await tr.send(await mkReq(id), { signal: signal() });
        const r = await tr.send(await mkReq(id, { payload: { synthetic: true, payload: { numero_de_cuba: "OTRO" } } }), { signal: signal() });
        assert.deepEqual([r.status, r.body.reason], [409, "payload_mismatch"]);
        const l = await tr.lookup(id, { signal: signal() });
        assert.equal(l.found && l.outcome, "accepted");
    });
    await scenario("04 concurrent POSTs register exactly one capture", async () => {
        const tr = createHttpSyncTransport(http(srv.url, user)); const id = crypto.randomUUID(); const req = await mkReq(id);
        const before = (await srv.stats()).receipts;
        const rs = await Promise.all(Array.from({ length: 8 }, () => tr.send(req, { signal: signal() })));
        assert.deepEqual(rs.map(r => r.status).sort(), [200, 200, 200, 200, 200, 200, 200, 201]);
        assert.equal(new Set(rs.map(r => r.body.server_id)).size, 1);
        assert.equal((await srv.stats()).receipts, before + 1);
    });
    await scenario("05/06 response lost after persistence: engine reconciles by GET, never POSTs twice", async () => {
        let lose = true;
        const c = await ctxOf({ hook: (m) => { if (m === "POST" && lose) { lose = false; throw new Error("connection reset after the server answered"); } } });
        const a = await c.add(1); const before = (await srv.stats()).receipts;
        const r1 = await c.run();
        assert.deepEqual([r1.stopped, (await c.rec(a)).state, (await c.rec(a)).uncertain], ["network", "retry_wait", true]);
        clock.t += 5000;
        const r2 = await c.run("B");
        assert.deepEqual([(await c.rec(a)).state, r2.reconciled, r2.sent, c.posts.n], ["synced", 1, 0, 1]);
        assert.equal((await srv.stats()).receipts, before + 1);
    });
    await scenario("07 original author different from the authenticated user", async () => {
        const c = await ctxOf(); const a = await c.add(1);
        const r = await c.run("A", { sessionUser: B });
        assert.deepEqual([r.paused, (await c.rec(a)).state, c.posts.n], ["different_user", "queued", 0]);
        const tr = createHttpSyncTransport(http(srv.url, { v: B }));
        const direct = await tr.send(await mkReq(crypto.randomUUID()), { signal: signal() });          // author A, session B
        assert.deepEqual([direct.status, direct.body.reason], [403, "author_mismatch"]);
    });
    await scenario("08 expired session (401) pauses and keeps the record queued", async () => {
        const c = await ctxOf({ user: { v: null } }); const a = await c.add(1);
        const r = await c.run();
        assert.deepEqual([r.paused, (await c.rec(a)).state, (await c.rec(a)).attempts], ["auth_required", "queued", 0]);
    });
    await scenario("09 capture without industrial permission goes to review, never synced", async () => {
        await srv.config({ grants: [] });
        const c = await ctxOf(); const a = await c.add(1); const before = (await srv.stats()).receipts;
        await c.run();
        assert.deepEqual([(await c.rec(a)).state, (await srv.stats()).receipts], ["requires_review", before]);
    });
    await scenario("10 readiness-only (consultation) snapshot never authorises a capture", async () => {
        const c = await ctxOf(); const a = await c.add(1, { snapshot: SNAP_CONSULT }); const before = (await srv.stats()).receipts;
        await c.run();
        const s = await c.rec(a);
        assert.deepEqual([s.state, (await srv.stats()).receipts], ["requires_review", before]);
    });
    await scenario("11 modified context: compatible warns, incompatible goes to review", async () => {
        const c = await ctxOf(); const ok = await c.add(1, { contextVersion: "ctx-compat" }); const bad = await c.add(2, { contextVersion: "ctx-incompat" });
        await c.run();
        const [a, b] = [await c.rec(ok), await c.rec(bad)];
        assert.deepEqual([a.state, a.warnings, b.state], ["synced_warning", ["context_changed_after_prepare"], "requires_review"]);
        assert.ok(a.serverRef && b.serverRef, "both are registered centrally (technical acceptance), neither is an approval");
    });
    await scenario("12 unverifiable context requires review and the result is reusable", async () => {
        const c = await ctxOf(); const a = await c.add(1, { contextVersion: "ctx-unknown" });
        await c.run();
        const s = await c.rec(a);
        assert.equal(s.state, "requires_review");
        const tr = createHttpSyncTransport(http(srv.url, user));
        const l = await tr.lookup(a.capture_id, { signal: signal() });
        assert.deepEqual([l.found, l.outcome], [true, "review"]);
    });
    await scenario("13 integrity conflict (declared checksum does not match the payload)", async () => {
        const tr = createHttpSyncTransport(http(srv.url, user)); const id = crypto.randomUUID();
        const r = await tr.send(await mkReq(id, { payload_sha256: "0".repeat(64) }), { signal: signal() });
        assert.deepEqual([r.status, r.body.reason], [409, "integrity_mismatch"]);
        assert.equal((await tr.lookup(id, { signal: signal() })).found, false);
    });
    await scenario("14 temporary server error retries with backoff and registers once", async () => {
        const c = await ctxOf(); const a = await c.add(1); const before = (await srv.stats()).receipts;
        await srv.config({ fail_next: 1 });
        const r1 = await c.run();
        assert.deepEqual([r1.stopped, (await c.rec(a)).state, (await srv.stats()).receipts], ["server_error", "retry_wait", before]);
        clock.t += 5000;
        await c.run("B");
        assert.deepEqual([(await c.rec(a)).state, (await srv.stats()).receipts], ["synced", before + 1]);
    });
    await scenario("18 an unverifiable 'success' reply is never synced", async () => {
        const forged = createHttpSyncTransport(async () => ({ status: 201, json: { outcome: "created", technical_acceptance: true } }));
        const r = await forged.send(await mkReq(crypto.randomUUID()), { signal: signal() });
        assert.deepEqual([r.status, r.body.reason], [409, "response_unverifiable"]);
        const wrongEcho = createHttpSyncTransport(async () => ({ status: 201, json: { outcome: "created", capture_id: crypto.randomUUID(), payload_sha256: "0".repeat(64), server_id: "srv-1", technical_acceptance: true } }));
        assert.equal((await wrongEcho.send(await mkReq(crypto.randomUUID()), { signal: signal() })).status, 409);
        const c = await ctxOf({ base: srv.url }); const a = await c.add(1);
        const dep = { ...c.deps("F"), transport: forged };
        await syncNow(dep);
        assert.equal((await c.rec(a)).state, "conflict");                                  // kept as a conflict, never `synced`
    });

    // ---- 15: restart of the receiver keeps every receipt; the engine reconciles instead of resending ----
    await scenario("15 recovery after a receiver restart", async () => {
        const c = await ctxOf(); const a = await c.add(1);
        let lose = true;
        const lossy = { ...c.deps("A"), transport: createHttpSyncTransport(http(srv.url, user, { after: (m) => { if (m === "POST" && lose) { lose = false; throw new Error("lost"); } } })) };
        await syncNow(lossy);
        assert.equal((await c.rec(a)).state, "retry_wait");
        const receiptsBefore = (await srv.stats()).receipts;
        await srv.stop();
        srv = await startServer(db);                                                         // new process, same database
        assert.equal((await srv.stats()).receipts, receiptsBefore);
        await srv.config({ grants: [[A, "MP1", "VINTO-P1-26"]] });
        clock.t += 5000;
        const fresh = { ...c.deps("B"), transport: createHttpSyncTransport(http(srv.url, user)) };
        const r = await syncNow(fresh);
        assert.deepEqual([(await c.rec(a)).state, r.reconciled, r.sent], ["synced", 1, 0]);
        assert.equal((await srv.stats()).receipts, receiptsBefore);
    });
    await srv.stop();

    // ---- 17: a DISABLED receiver accepts no writes ----
    const off = await startServer(join(tmp, "off.sqlite"), ["--disabled"]);
    await scenario("17 disabled receiver: 404, no row, the record is never marked synced", async () => {
        const c = await ctxOf({ base: off.url }); const a = await c.add(1);
        const r = await c.run();
        assert.deepEqual([r.stopped, (await c.rec(a)).state, (await off.stats()).receipts], ["server_error", "retry_wait", 0]);
        const direct = await fetch(off.url + "/api/offline/captures", { method: "POST", headers: { "content-type": "application/json", "x-synthetic-user": A }, body: JSON.stringify(await mkReq(crypto.randomUUID())) });
        assert.equal(direct.status, 404);
        assert.equal((await off.stats()).receipts, 0);
    });
    await off.stop();
    rmSync(tmp, { recursive: true, force: true });

    for (const [name, ok, detail] of results) console.log((ok ? "PASS " : "FAIL ") + name + (detail ? " :: " + detail : ""));
    assert.deepEqual(results.filter(r => !r[1]), []);
    assert.ok(results.length >= 16);
});
